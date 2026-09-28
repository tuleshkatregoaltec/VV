from uuid import uuid4

from app.config import settings
from app.core.cache import RedisCache


async def test_redis_roundtrip_and_prefix_cleanup_are_real():
    cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)
    prefix = "vv_migration_test:" + uuid4().hex + ":"
    try:
        assert await cache.ping()
        await cache.set(prefix + "one", {"count": 1}, expire=30)
        assert await cache.get(prefix + "one") == {"count": 1}
        await cache.clear_prefix(prefix)
        assert await cache.get(prefix + "one") is None
    finally:
        await cache.clear_prefix(prefix)
        if cache.redis is not None:
            await cache.redis.aclose()
