import logging
import platform
from typing import Any

import discord
from redis.asyncio import ConnectionPool
from redis.asyncio import Redis
from taskiq import AsyncBroker
from taskiq import InMemoryBroker
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
from taskiq_redis import ListQueueBroker
from typing_extensions import override

from bobuild.bo_discord import send_webhook
from bobuild.config import DiscordConfig
from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import get_var
from bobuild.utils import is_dev_env

if platform.system() == "Windows":
    # noinspection PyUnresolvedReferences
    import winloop

    winloop.install()

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

UNIQUE_PREFIX = "taskiq_unique"

_dummy_data: dict[str, str]
_default_expiration = 180 * 60


class UniqueLabelScheduleSource(LabelScheduleSource):
    def __init__(
            self,
            _broker: AsyncBroker,
            redis_url: str | None = None,
            expiration: int = _default_expiration,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        super().__init__(_broker)

        self.expiration = expiration
        self.unique_task_name = unique_task_name
        if redis_url is not None:
            self.pool: Redis | None = Redis.from_url(redis_url)
        else:
            global _dummy_data
            if not _dummy_data:
                _dummy_data = {}

    @override
    async def pre_send(self, task: ScheduledTask) -> None:
        try:
            global _dummy_data

            if task.task_name != self.unique_task_name:
                return

            if self.pool is None:
                return

            key = f"{UNIQUE_PREFIX}:{self.unique_task_name}"

            if self.pool is None:
                has_key = _dummy_data.get(key, None) is not None
            else:
                has_key = await self.pool.get(key) is not None

            if has_key:
                logger.info("task {} is already running, not starting a new one", task.task_name)
                task.task_name = "bobuild.tasks_bo.bo_dummy_task"
                return

            if self.pool is None:
                _dummy_data[key] = task.task_name
            else:
                await self.pool.set(key, 1, ex=self.expiration)

        except Exception as e:
            logger.exception(e)

    @override
    async def shutdown(self):
        if self.pool is not None:
            await self.pool.close()


# https://github.com/taskiq-python/taskiq/issues/271
class UniqueTaskMiddleware(TaskiqMiddleware):
    def __init__(
            self,
            redis_url: str | None = None,
            expiration: int = _default_expiration,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        super().__init__()

        self.expiration = expiration
        self.unique_task_name = unique_task_name

        if redis_url is not None:
            self.pool: Redis | None = Redis.from_url(redis_url)
        else:
            global _dummy_data
            if not _dummy_data:
                _dummy_data = {}

    @override
    async def post_save(
            self,
            message: TaskiqMessage,
            _: TaskiqResult[Any],
    ) -> None:
        # TODO: this never runs if worker is shut down mid-task?

        try:
            if message.task_name == self.unique_task_name:
                logger.info("deleting taskiq_unique key for task: '{}'", message.task_name)
                if self.pool is None:
                    global _dummy_data
                    del _dummy_data[message.task_name]
                else:
                    await self.pool.delete(f"{UNIQUE_PREFIX}:{message.task_name}")
        except Exception as e:
            logger.exception(e)

    @override
    async def shutdown(self):
        if self.pool is not None:
            await self.pool.close()


broker: AsyncBroker
scheduler: TaskiqScheduler
source: ScheduleSource
REDIS_URL: str

if is_dev_env():
    logger.info("using InMemoryBroker in development environment")

    broker = InMemoryBroker(
    ).with_middlewares(UniqueTaskMiddleware(
        unique_task_name="bobuild.tasks_bo.check_for_updates",
    ))

    source = UniqueLabelScheduleSource(
        broker,
        unique_task_name="bobuild.tasks_bo.check_for_updates",
    )

    scheduler = TaskiqScheduler(
        broker=broker,
        sources=[source],
    )
else:
    REDIS_URL = get_var("BO_REDIS_URL")
    PG_URL = get_var("BO_POSTGRES_URL")

    result_backend: AsyncpgResultBackend = AsyncpgResultBackend(
        dsn=PG_URL,
        keep_results=True,
        table_name="taskiq_result",
        field_for_task_id="Text",
        serializer=ORJSONSerializer(),
    )

    broker = ListQueueBroker(
        url=REDIS_URL,
    ).with_result_backend(
        result_backend
    ).with_serializer(
        ORJSONSerializer()
    ).with_middlewares(
        UniqueTaskMiddleware(
            redis_url=REDIS_URL,
            unique_task_name="bobuild.tasks_bo.check_for_updates",
        ),
    )

    source = UniqueLabelScheduleSource(
        broker,
        redis_url=REDIS_URL,
        unique_task_name="bobuild.tasks_bo.check_for_updates",
    )

    # source = RedisScheduleSource(
    #     url=REDIS_URL,
    #     serializer=ORJSONSerializer(),
    # )

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
            #
            # # TODO: this is getting kinda spaghetti-ey.
            # async for key in redis.scan_iter(match=f"{UNIQUE_PREFIX}:*"):
            #     logger.warning("leftover taskiq_unique key: {}", key)
            #     await redis.delete(key)
            #
            # for mw in broker.middlewares:
            #     if isinstance(mw, UniqueTaskMiddleware):
            #         tn = mw.unique_task_name
            #         for
            #
            #         if task:
            #             discord_cfg = DiscordConfig()
            #             await send_webhook(
            #                 url=discord_cfg.builds_webhook_url,
            #                 embed_title="Build cancelled! :warning:",
            #                 embed_color=discord.Color.yellow(),
            #                 embed_footer=task.task_id,
            #             )
            #

            logger.info("broker state: {}", broker.state)
            ids: dict[str, str]
            if ids := getattr(broker.state, "ids_", {}):
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
