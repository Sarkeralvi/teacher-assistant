from redis import Redis

from app.core.config import get_settings


def get_redis_client() -> Redis:
    settings = get_settings()
    # RQ stores pickled binary job payloads; decode_responses=True would
    # corrupt them, so this connection must stay in raw bytes mode.
    return Redis.from_url(settings.redis_url)
