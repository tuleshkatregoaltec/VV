import datetime
import json
import logging
from decimal import Decimal
from typing import Any, Optional

import redis.asyncio as redis

logger = logging.getLogger("RedisCache")


class RedisCache:
    """Redis-backed cache with JSON serialization and automatic expiration"""

    def __init__(self, redis_url: str, redis_password: str, default_expire: int = 600):
        self.redis_url = redis_url
        self.redis_password = redis_password
        self.default_expire = default_expire
        self.redis = None
        self.is_authed = False

        try:
            self.redis = redis.from_url(self.redis_url, password=self.redis_password)
            logger.info("Redis client initialized at %s", self.redis_url)
        except Exception as e:
            logger.error("Failed to initialize Redis client at %s: %s", self.redis_url, str(e))

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache by key, returns None if not found or Redis unavailable"""
        if not self.redis:
            return None

        try:
            value = await self.redis.get(key)
            if value is not None:
                try:
                    logger.debug("Cache hit for key: %s", key)
                    return json.loads(value)
                except Exception:
                    logger.warning("Failed to deserialize cache value for key: %s", key)
                    return value

            logger.debug("Cache miss for key: %s", key)
        except Exception as e:
            logger.error("Failed to get cache for key %s: %s", key, str(e))
        return None

    async def set(self, key: str, value: Any, expire: Optional[int] = None):
        """Set value in cache with optional expiration time in seconds"""
        if not self.redis:
            return

        def default(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            if isinstance(obj, (datetime.date, datetime.datetime)):
                return obj.isoformat()
            raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

        try:
            if not isinstance(value, str):
                value = json.dumps(value, default=default)

            await self.redis.set(key, value, ex=expire or self.default_expire)
            logger.debug("Cache set for key: %s", key)
        except Exception as e:
            logger.error("Failed to set cache for key %s: %s", key, str(e))

    async def delete(self, key: str):
        """Delete value from cache by key"""
        if not self.redis:
            return

        try:
            await self.redis.delete(key)
            logger.debug("Cache deleted for key: %s", key)
        except Exception as e:
            logger.error("Failed to delete cache for key %s: %s", key, str(e))

    async def clear(self, pattern: str = "*"):
        """Clear all keys matching pattern from cache"""
        if not self.redis:
            return

        try:
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
                logger.info(
                    "Cache cleared for pattern: %s (%d keys removed)",
                    pattern,
                    len(keys),
                )
            else:
                logger.debug("Cache clear called for pattern %s but no keys found", pattern)
        except Exception as e:
            logger.error("Failed to clear cache for pattern %s: %s", pattern, str(e))
