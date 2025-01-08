import asyncio
import datetime
import logging
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
from taskiq_redis import ListQueueBroker
from taskiq_redis import RedisAsyncResultBackend
from taskiq_redis import RedisScheduleSource

import bobuild.git
import bobuild.hg
from bobuild.config import GitConfig
from bobuild.config import MercurialConfig
from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import get_var
from bobuild.utils import is_dev_env

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

    redis_async_result: RedisAsyncResultBackend = RedisAsyncResultBackend(
        redis_url=REDIS_URL,
        result_ex_time=10 * 60,
        keep_results=False,
        timeout=30,
        serializer=ORJSONSerializer(),
    )

    broker = ListQueueBroker(
        url=REDIS_URL,
        result_backend=redis_async_result,
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


# TODO: Custom config dataclass!
def config_dep(context: Annotated[Context, TaskiqDepends()]) -> None:
    pass


def hg_config_dep(context: Annotated[Context, TaskiqDepends()]) -> MercurialConfig:
    pass


def git_config_dep(context: Annotated[Context, TaskiqDepends()]) -> GitConfig:
    pass


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
) -> None:
    logger.info("checking for updates")

    try:
        if await update_is_running():
            logger.info("skip checking updates, update in-progress flag is already set")
            return

        # TODO: do something with this?
        _ = await set_update_in_progress(True)

        # TODO: configuration object!
        hg_pkgs_incoming_task = bobuild.hg.incoming(hg_config.pkg_repo_path)
        hg_maps_incoming_task = bobuild.hg.incoming(hg_config.maps_repo_path)
        git_has_update_task = bobuild.git.repo_has_update(git_config.repo_path)

        hg_pkgs_inc, hg_maps_inc, git_has_update = await asyncio.gather(
            hg_pkgs_incoming_task,
            hg_maps_incoming_task,
            git_has_update_task,
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
