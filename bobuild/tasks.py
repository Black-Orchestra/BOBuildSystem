import asyncio

from taskiq import InMemoryBroker
from taskiq import TaskiqScheduler
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import ListQueueBroker
from taskiq_redis import RedisAsyncResultBackend
from taskiq_redis import RedisScheduleSource

from bobuild.utils import get_var
from bobuild.utils import is_dev_env

if is_dev_env():
    broker = InMemoryBroker()

    scheduler = TaskiqScheduler(
        broker=broker,
        sources=[LabelScheduleSource(broker)],
    )
else:
    REDIS_URL = get_var("BO_REDIS_URL")

    redis_async_result = RedisAsyncResultBackend(
        redis_url=REDIS_URL,
    )

    broker = ListQueueBroker(
        url=REDIS_URL,
        result_backend=redis_async_result,
    )

    redis_source = RedisScheduleSource(REDIS_URL)

    scheduler = TaskiqScheduler(
        broker=broker,
        sources=[redis_source],
    )


@broker.task(schedule=[{"cron": "*/5 * * * *"}])
async def test_task() -> None:
    await asyncio.sleep(5.5)
    print("All problems are solved!")
