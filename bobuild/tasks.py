import asyncio
import datetime
import logging
import platform
import shutil
from typing import Annotated

from redis.asyncio import ConnectionPool
from redis.asyncio import Redis
from taskiq import AsyncBroker
from taskiq import Context
from taskiq import InMemoryBroker
from taskiq import TaskiqDepends
from taskiq import TaskiqEvents
from taskiq import TaskiqScheduler
from taskiq import TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.serializers import ORJSONSerializer
from taskiq_pg import AsyncpgResultBackend
from taskiq_redis import ListQueueBroker
from taskiq_redis import RedisScheduleSource

import bobuild.git
import bobuild.hg
import bobuild.run
from bobuild.config import GitConfig
from bobuild.config import MercurialConfig
from bobuild.config import RS2Config
from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import copy_tree
from bobuild.utils import get_var
from bobuild.utils import is_dev_env

if platform.system() == "Windows":
    # noinspection PyUnresolvedReferences
    import winloop

    winloop.install()

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

broker: AsyncBroker
REDIS_URL: str

# TODO: just use redis in dev env too?
if is_dev_env():
    logger.info("using InMemoryBroker in development environment")

    broker = InMemoryBroker()

    source = LabelScheduleSource(broker)

    scheduler = TaskiqScheduler(
        broker=broker,
        sources=[source],
    )

    _update_timestamp = None


    async def set_update_in_progress(updating: bool) -> float | None:
        global _update_timestamp

        old_ts = _update_timestamp

        if updating:
            _update_timestamp = datetime.datetime.now(tz=datetime.timezone.utc).timestamp()
        else:
            _update_timestamp = None

        return old_ts


    async def update_is_running() -> bool:
        return _update_timestamp is not None
else:
    REDIS_URL = get_var("BO_REDIS_URL")
    PG_URL = get_var("BO_POSTRGRES_URL")

    result_backend: AsyncpgResultBackend = AsyncpgResultBackend(
        dsn=PG_URL,
        keep_results=True,
        table_name="taskiq_result",
        field_for_task_id="Text",
        serializer=ORJSONSerializer(),
    )

    broker = ListQueueBroker(
        url=REDIS_URL,
        result_backend=result_backend,
        serializer=ORJSONSerializer(),
    )

    redis_source = RedisScheduleSource(
        REDIS_URL,
        serializer=ORJSONSerializer(),
    )

    scheduler = TaskiqScheduler(
        broker=broker,
        sources=[redis_source],
    )


    @broker.on_event(TaskiqEvents.WORKER_STARTUP)
    async def startup(state: TaskiqState) -> None:
        state.redis = ConnectionPool.from_url(REDIS_URL)


    @broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
    async def shutdown(state: TaskiqState) -> None:
        await state.redis.disconnect()


    async def set_update_in_progress(updating: bool) -> float | None:
        ret = None

        if updating:
            get_task = await get_val.kiq("bo_check_for_updates_running")
            get_result = await get_task.wait_result()
            get_result.raise_for_result()
            old_timeout = get_result.return_value
            if old_timeout is not None:
                ret = float(old_timeout)

            val = str(datetime.datetime.now(tz=datetime.timezone.utc).timestamp())
            set_task = await set_val.kiq("bo_check_for_updates_running", val, persist=True)
            set_result = await set_task.wait_result()
            set_result.raise_for_error()
        else:
            delete_task = await delete_val.kiq("bo_check_for_updates_running")
            delete_result = await delete_task.wait_result()
            delete_result.raise_for_error()

        return ret


    async def update_is_running() -> bool:
        get_task = await get_val.kiq("bo_check_for_updates_running")
        get_result = await get_task.wait_result()
        get_result.raise_for_error()
        val = get_result.return_value
        # TODO: probably need to check the timestamp here (or somewhere)?
        return val is not None


def redis_dep(context: Annotated[Context, TaskiqDepends()]) -> Redis:
    return Redis(connection_pool=context.state.redis, decode_responses=True)


def hg_config_dep(_: Annotated[Context, TaskiqDepends()]) -> MercurialConfig:
    return MercurialConfig()


def git_config_dep(_: Annotated[Context, TaskiqDepends()]) -> GitConfig:
    return GitConfig()


def rs2_config_dep(_: Annotated[Context, TaskiqDepends()]) -> RS2Config:
    return RS2Config()


# TODO: why use these via tasks? Just use redis directly?!
@broker.task(timeout=30)
async def get_val(
        key: str,
        redis: Redis = TaskiqDepends(redis_dep),
) -> str | None:
    return await redis.get(key)


# TODO: why use these via tasks? Just use redis directly?!
@broker.task(timeout=30)
async def delete_val(
        key: str,
        redis: Redis = TaskiqDepends(redis_dep),
) -> None:
    await redis.delete(key)


# TODO: why use these via tasks? Just use redis directly?!
@broker.task(timeout=30)
async def set_val(
        key: str,
        value: str,
        redis: Redis = TaskiqDepends(redis_dep),
        persist: bool = False,
) -> None:
    await redis.set(key, value)
    if persist:
        await redis.persist(key)


async def dummy_hash_task() -> tuple[str, str]:
    return "", ""


def log_hash_diffs(hashes: tuple[str, str], name: str):
    if hashes[0] and hashes[1]:
        logger.info("{}: local hash: {}, remote hash: {}",
                    name, hashes[0], hashes[1])


# TODO: add custom logger that logs task IDs as extra!

# TODO: we can leave behind long-running garbage processes
#       such as from VNGame.exe brew and make. Do we make sure
#       in each module that they clean up their own processes?
#       Additionally, we need to make sure
# TODO: store PIDs of potentially problematic programs (VNGame.exe)
#       in Redis behind unique keys?
@broker.task(
    schedule=[{"cron": "*/1 * * * *"}],
    timeout=30 * 60,
)
async def check_for_updates(
        context: Annotated[Context, TaskiqDepends()],
        hg_config: MercurialConfig = TaskiqDepends(hg_config_dep),
        git_config: GitConfig = TaskiqDepends(git_config_dep),
        rs2_config: RS2Config = TaskiqDepends(rs2_config_dep),
) -> None:
    logger.info("checking for updates")

    try:
        # TODO: get running task status from Postgres?
        if await update_is_running():
            logger.info("skip checking updates, update in-progress flag is already set")
            return

        # Get task ID here, store it in DB and set in-progress state.

        # TODO: do something with this?
        old_update_timestamp = await set_update_in_progress(True)
        if old_update_timestamp:
            logger.warning(
                "old update in-progress flag was set, "
                "cleanup was potentially skipped: {}", old_update_timestamp)

        # TODO: run clone tasks in "parallel".

        if not await bobuild.git.repo_exists(git_config.repo_path):
            logger.info("git repo does not exist in '{}', cloning", git_config.repo_path)
            git_config.repo_path.mkdir(parents=True, exist_ok=True)
            await bobuild.git.clone_repo(git_config.repo_url, git_config.repo_path)

        # TODO: ensure hg config is correct every time here?
        # bobuild.hg.ensure_config(hg_config)

        if not await bobuild.hg.repo_exists(hg_config.pkg_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.pkg_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            await bobuild.hg.clone_repo(hg_config.pkg_repo_url, hg_config.pkg_repo_path)

        if not await bobuild.hg.repo_exists(hg_config.maps_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.maps_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            await bobuild.hg.clone_repo(hg_config.maps_repo_url, hg_config.maps_repo_path)

        hg_pkgs_incoming_task = bobuild.hg.incoming(hg_config.pkg_repo_path)
        hg_maps_incoming_task = bobuild.hg.incoming(hg_config.maps_repo_path)
        git_has_update_task = bobuild.git.repo_has_update(git_config.repo_path, git_config.branch)

        logger.info("running all repo update check tasks")
        hg_pkgs_inc, hg_maps_inc, git_has_update = await asyncio.gather(
            hg_pkgs_incoming_task,
            hg_maps_incoming_task,
            git_has_update_task,
        )

        logger.info("hg packages repo has update available: {}", hg_pkgs_inc)
        logger.info("hg maps repo has update available: {}", hg_maps_inc)
        logger.info("git repo has update available: {}", git_has_update)

        hash_diffs_tasks = []
        sync_tasks = []

        any_sync_task = any((hg_pkgs_inc, hg_maps_inc, git_has_update))

        # We add dummy hash diff tasks here to make sure the number of
        # tasks is always the same for the asyncio.await gather below.
        # TODO: there's a better way to do this, refactor later!
        if hg_pkgs_inc:
            hash_diffs_tasks.append(bobuild.hg.hash_diff(
                hg_config.pkg_repo_path, hg_config.pkg_repo_url))
            sync_tasks.append(bobuild.hg.sync(hg_config.pkg_repo_path))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        if hg_maps_inc:
            hash_diffs_tasks.append(bobuild.hg.hash_diff(
                hg_config.maps_repo_path, hg_config.maps_repo_url))
            sync_tasks.append(bobuild.hg.sync(hg_config.maps_repo_path))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        if git_has_update:
            hash_diffs_tasks.append(bobuild.git.hash_diff(
                git_config.repo_path, git_config.repo_url))
            sync_tasks.append(bobuild.hg.sync(git_config.repo_path))
        elif any_sync_task:
            hash_diffs_tasks.append(dummy_hash_task())

        if hash_diffs_tasks:
            logger.info("running {} hash diff tasks", len(hash_diffs_tasks))
            hg_pkg_hashes, hg_maps_hashes, git_hashes = await asyncio.gather(*hash_diffs_tasks)
            log_hash_diffs(hg_pkg_hashes, "hg packages repo")
            log_hash_diffs(hg_maps_hashes, "hg maps repo")
            log_hash_diffs(git_hashes, "git repo")
        else:
            logger.info("no hash diff tasks, all up to date")

        if sync_tasks:
            logger.info("running {} repo sync tasks", len(sync_tasks))
            await asyncio.gather(*sync_tasks)
        else:
            logger.info("no repo sync tasks, all up to date")
            return

        # 0. copy content to documents!
        # 1. compile code task
        # 2. list all packages and maps to brew (include the .u file)
        # 3. brew all content
        # 4. generate report (list number of warnings)
        # 5. upload content to workshop

        unpub_pkgs = rs2_config.unpublished_dir / "CookedPC/Packages/WW2"
        unpub_maps = rs2_config.unpublished_dir / "CookedPC/Maps/WW2"
        pub_pkgs = rs2_config.published_dir / "CookedPC/Packages/WW2"
        pub_maps = rs2_config.published_dir / "CookedPC/Maps/WW2"

        logger.info("removing dir: '{}'", unpub_pkgs)
        shutil.rmtree(unpub_pkgs, ignore_errors=True)
        logger.info("removing dir: '{}'", unpub_maps)
        shutil.rmtree(unpub_maps, ignore_errors=True)
        logger.info("removing dir: '{}'", pub_pkgs)
        shutil.rmtree(pub_pkgs, ignore_errors=True)
        logger.info("removing dir: '{}'", pub_maps)
        shutil.rmtree(pub_maps, ignore_errors=True)

        unpub_pkgs.mkdir(parents=True, exist_ok=True)
        unpub_maps.mkdir(parents=True, exist_ok=True)
        pub_pkgs.mkdir(parents=True, exist_ok=True)
        pub_maps.mkdir(parents=True, exist_ok=True)

        copy_tree(hg_config.pkg_repo_path, unpub_pkgs, "*.upk")

        await bobuild.run.vneditor_make(
            rs2_config.rs2_documents_dir,
            rs2_config.vneditor_exe,
        )

        roe_content: list[str] = [
            file.stem for file in
            unpub_maps.rglob(".roe")
        ]

        upk_content: list[str] = [
            file.name for file in
            unpub_pkgs.rglob(".upk")
        ]

        content_to_brew = ["WW2"] + roe_content + upk_content
        logger.info("total number of content to brew: {}", len(content_to_brew))

        await bobuild.run.vneditor_brew(
            rs2_config.rs2_documents_dir,
            rs2_config.vneditor_exe,
            content_to_brew,
        )

        ww2u = rs2_config.published_dir / "CookedPC/WW2.u"
        logger.info("patching WW2.u file in: '{}'", ww2u)
        await bobuild.run.patch_shader_cache(
            ww2u,
            "SeekFreeShaderCache",
            "WW2GameInfo.DummyObject",
        )

        await asyncio.sleep(2 * 60)
        print("DONE!")
        print(context.message)
        print(context.state)

    except Exception as e:
        logger.error("error running task: {}: {}: {}",
                     context.message, type(e).__name__, e)
        raise
    finally:
        await set_update_in_progress(False)
