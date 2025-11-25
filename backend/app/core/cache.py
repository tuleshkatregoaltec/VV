import redis.asyncio as redis
import json
from typing import Any, Optional
from decimal import Decimal
import datetime
import logging

# Configure logging
logger = logging.getLogger("RedisCache")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)


class RedisCache:
    def __init__(self, redis_url: str = "redis://localhost", default_expire: int = 600):
        self.redis_url = redis_url
        self.default_expire = default_expire
        try:
            self.redis = redis.from_url(self.redis_url)
            logger.info("Connected to Redis at %s", self.redis_url)
        except Exception as e:
            logger.error("Failed to connect to Redis at %s: %s", self.redis_url, str(e))

    async def get(self, key: str) -> Optional[Any]:
        try:
            value = await self.redis.get(key)
            if value is not None:
                try:
                    logger.info("Cache hit for key: %s", key)
                    return json.loads(value)
                except Exception:
                    logger.warning("Failed to deserialize cache value for key: %s", key)
                    return value
            logger.info("Cache miss for key: %s", key)
        except Exception as e:
            logger.error("Failed to get cache for key %s: %s", key, str(e))
        return None

    async def set(self, key: str, value: Any, expire: Optional[int] = None):
        def default(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, (datetime.date, datetime.datetime)):
                return obj.isoformat()
            raise TypeError(
                f"Object of type {obj.__class__.__name__} is not JSON serializable"
            )

        try:
            if not isinstance(value, str):
                value = json.dumps(value, default=default)
            await self.redis.set(key, value, ex=expire or self.default_expire)
            logger.info("Cache set for key: %s", key)
        except Exception as e:
            logger.error("Failed to set cache for key %s: %s", key, str(e))

    async def delete(self, key: str):
        try:
            await self.redis.delete(key)
            logger.info("Cache deleted for key: %s", key)
        except Exception as e:
            logger.error("Failed to delete cache for key %s: %s", key, str(e))

    async def clear(self, pattern: str = "*"):
        try:
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
                logger.info("Cache cleared for pattern: %s", pattern)
        except Exception as e:
            logger.error("Failed to clear cache for pattern %s: %s", pattern, str(e))
