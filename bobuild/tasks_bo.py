import asyncio
import datetime
import shutil
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated

from redis.asyncio import Redis
from taskiq import Context
from taskiq import TaskiqDepends

import bobuild.git
import bobuild.hg
import bobuild.run
import bobuild.workshop
from bobuild.config import GitConfig
from bobuild.config import MercurialConfig
from bobuild.config import RS2Config
from bobuild.log import logger
from bobuild.tasks import broker
from bobuild.utils import copy_tree
from bobuild.utils import is_dev_env
from bobuild.workshop import find_map_names
from bobuild.workshop import iter_maps

_repo_dir = Path(__file__).parent.resolve()

if is_dev_env():
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
    async def set_update_in_progress(updating: bool) -> float | None:
        ret = None

        if updating:
            get_task = await get_val.kiq("bo_check_for_updates_running")
            get_result = await get_task.wait_result()
            get_result.raise_for_error()
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


def prepare_map_for_sws(
        publishedfileid: int,
        map_name: str,
        template_img: Path,
        template_vdf: Path,
        staging_dir: Path,
        content_folder: Path,
        git_hash: str,
        hg_pkg_hash: str,
        hg_maps_hash: str,
        changenote: str,
):
    preview_file = staging_dir / f"BOBetaMapImg_{map_name}.png"
    bobuild.workshop.draw_map_preview_file(
        map_name=map_name,
        template_file=template_img,
        output_file=preview_file,
    )

    map_vdf_file = staging_dir / f"{map_name}.vdf"

    bobuild.workshop.write_map_sws_config(
        out_file=map_vdf_file,
        template_file=template_vdf,
        map_name=map_name,
        publishedfileid=publishedfileid,
        content_folder=content_folder,
        preview_file=preview_file,
        git_hash=git_hash,
        hg_pkg_hash=hg_pkg_hash,
        hg_maps_hash=hg_maps_hash,
        changenote=changenote,
    )


@broker.task(
    timeout=10,
    task_name="bobuild.tasks_bo.bo_dummy_task",
)
async def bo_dummy_task():
    logger.info("running dummy task to do nothing")


# TODO: add custom logger that logs task IDs as extra!

# TODO: we can leave behind long-running garbage processes
#       such as from VNGame.exe brew and make. Do we make sure
#       in each module that they clean up their own processes?
#       Additionally, we need to make sure
# TODO: store PIDs of potentially problematic programs (VNGame.exe)
#       in Redis behind unique keys?
# TODO: return a result from this task?
# TODO: store hashes in metadata so we can retry a failed task for the hashes?
#       For tasks that begin successfully but then fail for some reason halfway?
@broker.task(
    schedule=[{"cron": "*/1 * * * *"}],
    timeout=30 * 60,
    task_name="bobuild.tasks_bo.check_for_updates",
)
async def check_for_updates(
        context: Annotated[Context, TaskiqDepends()],
        hg_config: MercurialConfig = TaskiqDepends(hg_config_dep),
        git_config: GitConfig = TaskiqDepends(git_config_dep),
        rs2_config: RS2Config = TaskiqDepends(rs2_config_dep),
) -> None:
    started_updating = False

    logger.info("checking for updates")

    try:
        # TODO: get running task status from Postgres?
        if await update_is_running():
            logger.info("skip checking updates, update in-progress flag is already set")
            return

        # Get task ID here, store it in DB and set in-progress state.
        started_updating = True

        # TODO: do something with this?
        old_update_timestamp = await set_update_in_progress(True)
        if old_update_timestamp:
            logger.warning(
                "old update in-progress flag was set, "
                "cleanup was potentially skipped: {}", old_update_timestamp)

        bobuild.hg.ensure_config(hg_config)
        await bobuild.run.ensure_vneditor_modpackages_config(
            rs2_config=rs2_config,
            mod_packages=["WW2"],
        )

        clone_tasks = []

        cloned_git = False
        if not await bobuild.git.repo_exists(git_config.repo_path):
            logger.info("git repo does not exist in '{}', cloning", git_config.repo_path)
            git_config.repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.git.clone_repo(git_config.repo_url, git_config.repo_path))
            cloned_git = True

        cloned_hg_pkgs = False
        if not await bobuild.hg.repo_exists(hg_config.pkg_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.pkg_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.hg.clone_repo(hg_config.pkg_repo_url, hg_config.pkg_repo_path))
            cloned_hg_pkgs = True

        cloned_hg_maps = False
        if not await bobuild.hg.repo_exists(hg_config.maps_repo_path):
            logger.info("hg repo does not exist in '{}', cloning", hg_config.maps_repo_path)
            hg_config.pkg_repo_path.mkdir(parents=True, exist_ok=True)
            clone_tasks.append(bobuild.hg.clone_repo(hg_config.maps_repo_url, hg_config.maps_repo_path))
            cloned_hg_maps = True

        if clone_tasks:
            logger.info("running {} clone tasks", len(clone_tasks))
            await asyncio.gather(*clone_tasks)

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
            sync_tasks.append(bobuild.git.sync_repo(git_config.repo_path, git_config.branch))
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
            if any((cloned_git, cloned_hg_pkgs, cloned_hg_maps)):
                # TODO: do something here? Log?
                pass
            else:
                logger.info("no further work to be done")
                return

        git_hash = await bobuild.git.get_local_hash(git_config.repo_path)
        hg_pkgs_hash = await bobuild.hg.get_local_hash(hg_config.pkg_repo_path)
        hg_maps_hash = await bobuild.hg.get_local_hash(hg_config.maps_repo_path)

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
        # TODO: this is done somewhat manually for now.
        # Determine directories for other maps automatically.
        map_to_unpub_dir = {
            "RRTE-Beach_Invasion_Sim": "BeachInvasionSim",
        }

        map_unpub_dirs: dict[str, Path] = {}
        for m in iter_maps(hg_config.maps_repo_path):
            mn = m.stem
            if mn in map_to_unpub_dir:
                map_unpub_dir = unpub_maps / map_to_unpub_dir[mn]
            else:
                map_unpub_dir = unpub_maps / m.parent

            map_unpub_dirs[mn] = map_unpub_dir

            logger.info("map '{}': Unpublished dir: '{}'", mn, map_unpub_dir)
            map_unpub_dir.mkdir(parents=True, exist_ok=True)
            copy_tree(m.parent, map_unpub_dir, "*.roe")

        # TODO: use UE-Library to find references to required sublevels?

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

        ww2u_staging_dir = _repo_dir / "workshop/generated/ww2u_staging/"
        logger.info("preparing main SWS item in '{}'", ww2u_staging_dir)
        ww2u_staging_dir.mkdir(parents=True, exist_ok=True)

        map_names = find_map_names(pub_maps)
        logger.info("found {} maps for workshop uploads", len(map_names))

        fs: list[Future] = []
        with ThreadPoolExecutor() as executor:
            template_img = _repo_dir / "workshop/bo_beta_workshop_map.png"
            template_vdf = _repo_dir / "workshop/BOBetaMapTemplate.vdf"
            for map_name in map_names:
                staging_dir = _repo_dir / "workshop/generated/sws_map_staging/" / map_name
                staging_dir.mkdir(parents=True, exist_ok=True)

                changenote = fr"""
Git commit: {git_hash}.
Mercurial packages commit: {hg_pkgs_hash}.
Mercurial maps commit: {hg_maps_hash}.
                """

                try:
                    publishedfileid = rs2_config.bo_dev_beta_map_ids[map_name]
                except KeyError:
                    logger.warning("no SWS ID for map '{}', skipping", map_name)
                    continue

                try:
                    content_folder = map_unpub_dirs[map_name]
                except KeyError:
                    logger.error("failed to determine contentfolder for map '{}'", map_name)
                    continue

                executor.submit(
                    prepare_map_for_sws,
                    publishedfileid=publishedfileid,
                    map_name=map_name,
                    template_img=template_img,
                    template_vdf=template_vdf,
                    staging_dir=staging_dir,
                    git_hash=git_hash,
                    hg_pkg_hash=hg_pkgs_hash,
                    hg_maps_hash=hg_maps_hash,
                    changenote=changenote,
                    content_folder=content_folder,
                )

        exs: list[str] = []
        for f in fs:
            ex = f.exception()
            if ex:
                logger.error("future {} failed with error: {}: {}", f, type(ex).__name__, ex)
                exs.append(str(ex))
        if exs:
            ex_string = "\n".join(exs)
            raise RuntimeError("failed to render map preview files: {}", ex_string)

        # TODO: it's possible a new map is added to the repo, which is not listed
        #   in map_ids_factory(). Is there a nice way to automate creation of new
        #   workshop items? Probably not? At the very least, this task should post
        #   a notification when such a map is found.

        logger.info("task {} done", context.message)

    except Exception as e:
        logger.error("error running task: {}: {}: {}",
                     context.message, type(e).__name__, e)
        raise
    finally:
        if started_updating:
            await set_update_in_progress(False)
