from functools import wraps
from typing import Callable, Any
import logging

from backend.app.core.cache import RedisCache
from backend.app.config import settings

logger = logging.getLogger(__name__)

# Instantiate cache once to be used by decorators
cache = RedisCache(settings.REDIS_URL)


def serialize_result(result: Any) -> Any:
    """
    Helper to convert SQLModel/Pydantic objects to dicts for caching.
    """
    if isinstance(result, list):
        return [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in result
        ]
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result


def cached_endpoint(prefix: str, expire: int = 600):
    """
    Decorator to cache FastAPI endpoint responses.
    - prefix: The Redis key prefix (e.g., 'developers')
    - expire: Time in seconds (default 10 mins)
    """

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ignored_keys = {"session", "current_user", "request", "response"}

            key_params = {
                k: v
                for k, v in kwargs.items()
                if k not in ignored_keys and v is not None
            }

            param_str = ":".join(f"{k}={v}" for k, v in sorted(key_params.items()))
            cache_key = f"{prefix}:{param_str}" if param_str else prefix

            cached_data = await cache.get(cache_key)
            if cached_data:
                return cached_data

            result = await func(*args, **kwargs)

            try:
                serialized_data = serialize_result(result)
                await cache.set(cache_key, serialized_data, expire=expire)
            except Exception as e:
                logger.error("Cache set error for %s: %s", cache_key, e)

            return result

        return wrapper

    return decorator
