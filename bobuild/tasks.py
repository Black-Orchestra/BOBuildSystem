import logging
import platform
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlunparse

import discord
from redis.asyncio import ConnectionPool
from redis.asyncio import Redis
from redis.asyncio.connection import parse_url
from redis.asyncio.lock import Lock
from taskiq import AsyncBroker
from taskiq import ScheduleSource
from taskiq import ScheduledTask
from taskiq import TaskiqEvents
from taskiq import TaskiqMessage
from taskiq import TaskiqMiddleware
from taskiq import TaskiqResult
from taskiq import TaskiqScheduler
from taskiq import TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.serializers import ORJSONSerializer
from taskiq_pg import AsyncpgResultBackend
from taskiq_redis import PubSubBroker
from typing_extensions import override

from bobuild.bo_discord import send_webhook
from bobuild.config import DiscordConfig
from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import get_var

if platform.system() == "Windows":
    # noinspection PyUnresolvedReferences
    import winloop

    winloop.install()

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

UNIQUE_PREFIX = "taskiq_unique"

_default_expiration = 180 * 60

bo_build_lock_name = "bobuild.tasks_bo.check_for_updates__LOCK"


class UniqueLabelScheduleSource(LabelScheduleSource):
    """Custom schedule source that prevents a task from being
    sent to the broker if an instance of it is already running.
    """

    def __init__(
            self,
            _broker: AsyncBroker,
            redis_url: str,
            expiration: int = _default_expiration,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        super().__init__(_broker)

        self.expiration = expiration
        self.unique_task_name = unique_task_name
        self.pool = Redis.from_url(redis_url)

    @override
    async def pre_send(self, task: ScheduledTask) -> None:
        """TODO: this is actually not 100% reliable!
            - If this expires without having consumed the tasks, we will
              queue another task! Needs a better solution!
        TODO: did using PubSub solve the above problem?
        """
        lock: Lock | None = None
        acquired = False
        try:
            lock = self.pool.lock(bo_build_lock_name, timeout=180 * 60, blocking=True)
            acquired = await lock.acquire(blocking=True, blocking_timeout=0.1)  # type: ignore[union-attr]
            if acquired:
                # There is currently no task running, free to start a new one.
                return
            else:
                logger.info("task {} is already running, not starting a new one", task.task_name)
                task.task_name = "bobuild.tasks_bo.bo_dummy_task"
        except Exception as e:
            logger.exception(e)
        finally:
            if lock and acquired:
                try:
                    await lock.release()
                except Exception as e:
                    logger.error("error releasing lock: {}: {}",
                                 type(e).__name__, e)

    @override
    async def shutdown(self):
        await self.pool.close()


# https://github.com/taskiq-python/taskiq/issues/271
class UniqueTaskMiddleware(TaskiqMiddleware):
    """Used together with UniqueLabelScheduleSource to ensure
    unique task is cleaned up after it finishes in order to allow
    a new instance of the task to be started.
    """

    def __init__(
            self,
            redis_url: str,
            expiration: int = _default_expiration,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        super().__init__()

        self.expiration = expiration
        self.unique_task_name = unique_task_name
        self.pool = Redis.from_url(redis_url)

    @override
    async def post_save(
            self,
            message: TaskiqMessage,
            _: TaskiqResult[Any],
    ) -> None:
        # TODO: what happens if task never saves its result?
        # TODO: this never runs if worker is shut down mid-task?
        try:
            if message.task_name == self.unique_task_name:
                logger.info("deleting taskiq_unique key for task: '{}'", message.task_name)
                await self.pool.delete(f"{UNIQUE_PREFIX}:{message.task_name}")
        except Exception as e:
            logger.exception(e)

    @override
    async def shutdown(self):
        await self.pool.close()


broker: AsyncBroker
scheduler: TaskiqScheduler
source: ScheduleSource
REDIS_URL = get_var("BO_REDIS_URL")

if redis_hostname := get_var("BO_REDIS_HOSTNAME", None):
    parts = urlparse(REDIS_URL)
    hostname = parse_url(REDIS_URL)["host"]

    logger.info("replacing hostname in Redis URL: '{}' -> '{}'",
                hostname, redis_hostname)

    # TODO: this is unbelievably fucking hacky. Find a proper
    #   way to do this whole thing here!
    new_netloc = parts.netloc.replace(hostname, redis_hostname)
    parts = parts._replace(netloc=new_netloc)

    REDIS_URL = str(urlunparse(parts))

# TODO: the better way to do this would be to have a separate module for
#   scheduler that does not cause this env var to be checked!
is_scheduler_only = get_var("BO_TASK_SCHEDULER", "0") == "1"
if is_scheduler_only:
    logger.info("running in scheduler-only mode, allowing empty BO_POSTGRES_URL")
    PG_URL = get_var("BO_POSTGRES_URL", None)
else:
    PG_URL = get_var("BO_POSTGRES_URL")

result_backend: AsyncpgResultBackend | None = None

if is_scheduler_only and PG_URL is None:
    logger.info(
        "running in scheduler-only mode, "
        "BO_POSTGRES_URL is not set, not creating result backend")
else:
    result_backend = AsyncpgResultBackend(
        dsn=PG_URL,
        keep_results=True,
        table_name="taskiq_result",
        field_for_task_id="Text",
        serializer=ORJSONSerializer(),
    )

broker = PubSubBroker(
    url=REDIS_URL,
).with_serializer(
    ORJSONSerializer()
).with_middlewares(
    UniqueTaskMiddleware(
        redis_url=REDIS_URL,
        unique_task_name="bobuild.tasks_bo.check_for_updates",
    ),
)

if result_backend is not None:
    broker = broker.with_result_backend(result_backend)

source = UniqueLabelScheduleSource(
    broker,
    redis_url=REDIS_URL,
    unique_task_name="bobuild.tasks_bo.check_for_updates",
)

scheduler = TaskiqScheduler(
    broker=broker,
    sources=[source],
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState) -> None:
    state.redis = ConnectionPool.from_url(REDIS_URL)


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def shutdown(state: TaskiqState) -> None:
    try:
        pool: ConnectionPool = state.redis
        redis: Redis = Redis.from_pool(pool)

        # TODO: can we even do this here? Need some neat way of detecting cancelled tasks!
        # TODO: this is getting kinda spaghetti-ey.

        logger.info("broker state: {}", state)
        ids: dict[str, str]
        if ids := getattr(state, "ids_", {}):
            for task_id in ids:
                discord_cfg = DiscordConfig()
                await send_webhook(
                    url=discord_cfg.builds_webhook_url,
                    embed_title="Build cancelled! :warning:",
                    embed_color=discord.Color.yellow(),
                    embed_footer=task_id,
                )

        await redis.close()
        await pool.disconnect()

    except Exception as e:
        logger.exception(e)
