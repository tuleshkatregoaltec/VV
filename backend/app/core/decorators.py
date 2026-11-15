import asyncio
import inspect
import json
import logging
import time
from functools import wraps
from typing import Callable

from fastapi.encoders import jsonable_encoder
from fastapi.params import Depends as DependsParam
from pydantic import BaseModel

from app.config import settings
from app.core.cache import RedisCache

logger = logging.getLogger(__name__)

cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)

# Single flight. In this process, concurrent misses for one key share one computation. Across
# worker processes, the first miss takes a Redis fill lock and the others wait for its result in
# the cache, computing it themselves only if it has not arrived within LOCK_WAIT_SECONDS.
LOCK_TTL_SECONDS = 120
LOCK_WAIT_SECONDS = 60
LOCK_POLL_SECONDS = 0.25
_inflight: dict[str, asyncio.Future] = {}


def _is_dependency_parameter(parameter: inspect.Parameter) -> bool:
    return isinstance(parameter.default, DependsParam)


def _build_cache_key(prefix: str, signature: inspect.Signature, *args, **kwargs) -> str:
    ignored_names = {"request", "response"}
    bound_arguments = signature.bind_partial(*args, **kwargs)
    bound_arguments.apply_defaults()

    cacheable_arguments = {}
    for name, parameter in signature.parameters.items():
        if name in ignored_names:
            continue

        value = bound_arguments.arguments.get(name, inspect.Parameter.empty)
        # Dependencies are skipped (auth context, sessions) unless they resolve to a request model,
        # such as the filters a dependency gathers from query parameters: those shape the response.
        if _is_dependency_parameter(parameter) and not isinstance(value, BaseModel):
            continue
        if value is inspect.Parameter.empty or value is None:
            continue

        cacheable_arguments[name] = jsonable_encoder(value)

    if not cacheable_arguments:
        return prefix

    encoded_arguments = json.dumps(
        cacheable_arguments,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"{prefix}:{encoded_arguments}"


async def _wait_for_peer(cache_key: str):
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(LOCK_POLL_SECONDS)
        cached_data = await cache.get(cache_key)
        if cached_data is not None:
            return cached_data
    return None


async def _fill(cache_key: str, func: Callable, expire: int, args, kwargs):
    token = await cache.acquire_lock(cache_key, ttl_seconds=LOCK_TTL_SECONDS)
    if token is None:
        cached_data = await _wait_for_peer(cache_key)
        if cached_data is not None:
            return cached_data
        logger.warning("Cache fill for %s did not arrive; computing it here", cache_key)
    try:
        result = await func(*args, **kwargs)
        try:
            await cache.set(cache_key, jsonable_encoder(result), expire=expire)
        except Exception as e:
            logger.error("Cache set error for %s: %s", cache_key, e)
        return result
    finally:
        if token:
            await cache.release_lock(cache_key, token)


def _forget(cache_key: str, task: asyncio.Future) -> None:
    if _inflight.get(cache_key) is task:
        del _inflight[cache_key]
    if not task.cancelled():
        task.exception()  # Retrieved here, so a fill whose callers all left logs nothing.


def cached_endpoint(prefix: str, expire: int = 600):
    """Cache endpoint responses in Redis, computing each missing key once at a time."""

    def decorator(func: Callable):
        signature = inspect.signature(func)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            cache_key = _build_cache_key(prefix, signature, *args, **kwargs)

            cached_data = await cache.get(cache_key)
            if cached_data is not None:
                return cached_data

            task = _inflight.get(cache_key)
            if task is None:
                task = asyncio.ensure_future(_fill(cache_key, func, expire, args, kwargs))
                _inflight[cache_key] = task
                task.add_done_callback(lambda done, key=cache_key: _forget(key, done))
            # A caller that goes away does not cancel the fill the others are waiting for.
            return await asyncio.shield(task)

        return wrapper

    return decorator
