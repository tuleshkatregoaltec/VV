import redis.asyncio as redis
import json
from typing import Any, Optional
from decimal import Decimal
import datetime
import logging

logger = logging.getLogger("RedisCache")

class RedisCache:
    def __init__(self, redis_url: str = "redis://localhost", default_expire: int = 600):
        self.redis_url = redis_url
        self.default_expire = default_expire
        self.redis = None
        
        try:
            # Create the Redis client
            self.redis = redis.from_url(self.redis_url)
            logger.info("Redis client initialized at %s", self.redis_url)
        except Exception as e:
            logger.error("Failed to initialize Redis client at %s: %s", self.redis_url, str(e))

    async def get(self, key: str) -> Optional[Any]:
        if not self.redis:
            return None
            
        try:
            value = await self.redis.get(key)
            if value is not None:
                try:
                    # DEBUG level: Won't show in console, will show in debug.log
                    logger.debug("Cache hit for key: %s", key)
                    return json.loads(value)
                except Exception:
                    logger.warning("Failed to deserialize cache value for key: %s", key)
                    return value
            
            # DEBUG level
            logger.debug("Cache miss for key: %s", key)
        except Exception as e:
            # ERROR level: Always show this
            logger.error("Failed to get cache for key %s: %s", key, str(e))
        return None

    async def set(self, key: str, value: Any, expire: Optional[int] = None):
        if not self.redis:
            return

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
            logger.debug("Cache set for key: %s", key)
        except Exception as e:
            logger.error("Failed to set cache for key %s: %s", key, str(e))

    async def delete(self, key: str):
        if not self.redis:
            return
            
        try:
            await self.redis.delete(key)
            logger.debug("Cache deleted for key: %s", key)
        except Exception as e:
            logger.error("Failed to delete cache for key %s: %s", key, str(e))

    async def clear(self, pattern: str = "*"):
        if not self.redis:
            return

        try:
            keys = await self.redis.keys(pattern)
            if keys:
                await self.redis.delete(*keys)
                logger.info("Cache cleared for pattern: %s (%d keys removed)", pattern, len(keys))
            else:
                logger.debug("Cache clear called for pattern %s but no keys found", pattern)
        except Exception as e:
            logger.error("Failed to clear cache for pattern %s: %s", pattern, str(e))
