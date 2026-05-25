from rq import Queue

from app.core.config import get_settings
from app.redis_client import get_redis_client


def get_default_queue() -> Queue:
    settings = get_settings()
    return Queue(settings.rq_default_queue, connection=get_redis_client())
