import logging
import platform

from redis.asyncio import ConnectionPool
from taskiq import AsyncBroker
from taskiq import InMemoryBroker
from taskiq import ScheduleSource
from taskiq import TaskiqEvents
from taskiq import TaskiqScheduler
from taskiq import TaskiqState
from taskiq.schedule_sources import LabelScheduleSource
from taskiq.serializers import ORJSONSerializer
from taskiq_pg import AsyncpgResultBackend
from taskiq_redis import ListQueueBroker
from taskiq_redis import RedisScheduleSource

from bobuild.log import InterceptHandler
from bobuild.log import logger
from bobuild.utils import get_var
from bobuild.utils import is_dev_env

if platform.system() == "Windows":
    # noinspection PyUnresolvedReferences
    import winloop

    winloop.install()

logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

broker: AsyncBroker
scheduler: TaskiqScheduler
source: ScheduleSource
REDIS_URL: str

if is_dev_env():
    logger.info("using InMemoryBroker in development environment")

    broker = InMemoryBroker()

    source = LabelScheduleSource(broker)

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
    )

    source = RedisScheduleSource(
        url=REDIS_URL,
        serializer=ORJSONSerializer(),
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
        await state.redis.disconnect()
