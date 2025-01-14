import logging
import platform
from typing import Any

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

from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import get_var
from bobuild.utils import is_dev_env

if platform.system() == "Windows":
    # noinspection PyUnresolvedReferences
    import winloop

    winloop.install()

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


class UniqueLabelScheduleSource(LabelScheduleSource):
    def __init__(
            self,
            _broker: AsyncBroker,
            redis_url: str | None = None,
            expiration: int = 60 * 60,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        # TODO: when redis_url is not set, use in-memory dict!

        super().__init__(_broker)

        self.expiration = expiration
        self.unique_task_name = unique_task_name
        if redis_url is not None:
            self.pool: Redis | None = Redis.from_url(redis_url)

    @override
    async def pre_send(self, task: ScheduledTask) -> None:
        if task.task_name != self.unique_task_name:
            return

        if self.pool is None:
            return

        key = f"taskiq_unique:{self.unique_task_name}"

        if await self.pool.get(key):
            logger.info("task {} is already running, not starting a new one", task.task_name)
            task.task_name = "bobuild.tasks_bo.bo_dummy_task"
            return
        else:
            await self.pool.set(key, 1, ex=self.expiration)

        return

    @override
    async def shutdown(self):
        if self.pool is not None:
            await self.pool.close()


# https://github.com/taskiq-python/taskiq/issues/271
class UniqueTaskMiddleware(TaskiqMiddleware):
    def __init__(
            self,
            redis_url: str | None = None,
            expiration: int = 60 * 60,
            unique_task_name: str | None = None,  # TODO: take a list here if needed?
    ) -> None:
        # TODO: when redis_url is not set, use in-memory dict!

        super().__init__()

        self.expiration = expiration
        self.unique_task_name = unique_task_name
        if redis_url is not None:
            self.pool: Redis | None = Redis.from_url(redis_url)

    @override
    async def post_save(
            self,
            message: TaskiqMessage,
            _: TaskiqResult[Any],
    ) -> None:
        if message.task_name == self.unique_task_name:
            logger.info("deleting taskiq_unique key for task: '{}'", message.task_name)
            await self.pool.delete(f"taskiq_unique:{message.task_name}")

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
        await state.redis.disconnect()
