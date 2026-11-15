"""Cache warehouse-wide CRM lease pages per data release.

The dashboard, Assets › Renewals and the My-areas area list read the same lease relation for
every organization. Their answers change only when the lease, sale-match or geography sources
change (a vv-dxbi-sync load) or the day turns, so they are stored in Redis under a key made of
the sources' metadata revision, the request's parameters (which include the as-of date) and a
code version. A load changes the sources' parts, which changes the key: the first view after a
load recomputes and nothing stale is served, with no invalidation call to forget. The revision
is read from system.tables/parts/mutations only (milliseconds, no data scanned).

While a source mutation is running, or the metadata cannot be read, the revision is unknown and
the page is computed live and not stored.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from crm_rental_sql import DEPENDENCY_STATE_SQL, TRANSFORM_REVISION, dependency_revision
from pydantic import BaseModel

from app.clickhouse.client import query
from app.config import settings
from app.core.cache import RedisCache

logger = logging.getLogger(__name__)

# Bump when a cached page's shape or SQL changes, so an old answer is never served by new code.
CACHE_VERSION = "1"
PREFIX = "crm:lead-pages"
# Keys already change with every release and as-of day; the TTL only bounds Redis memory.
TTL_SECONDS = 12 * 3600

ModelT = TypeVar("ModelT", bound=BaseModel)

_cache: RedisCache | None = None
_inflight: dict[str, asyncio.Future] = {}


def _cache_client() -> RedisCache:
    global _cache
    if _cache is None:
        _cache = RedisCache(settings.REDIS_URL, settings.REDIS_PASSWORD)
    return _cache


async def lead_data_revision() -> str | None:
    """A digest of the lease sources' tables, parts and pending mutations; None if unknown."""
    try:
        return dependency_revision(await query(DEPENDENCY_STATE_SQL))
    except ValueError:
        # A mutation is running or a source is missing: there is no stable release to key on.
        return None
    except Exception:
        logger.warning("CRM lease source revision unavailable", exc_info=True)
        return None


def _key(name: str, revision: str, params: dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(params, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()[:32]
    code = hashlib.sha256(f"{CACHE_VERSION}:{TRANSFORM_REVISION}".encode()).hexdigest()[:12]
    release = hashlib.sha256(revision.encode()).hexdigest()[:24]
    return f"{PREFIX}:{code}:{name}:{release}:{digest}"


async def cached(
    name: str,
    params: dict[str, Any],
    model: type[ModelT],
    compute: Callable[[], Awaitable[ModelT]],
) -> ModelT:
    """Serve `compute()`'s answer for this lease data release and parameters, computing it once.

    Identical concurrent requests in this worker share one computation.
    """
    return await cached_for(name, await lead_data_revision(), params, model, compute)


async def cached_for(
    name: str,
    revision: str | None,
    params: dict[str, Any],
    model: type[ModelT],
    compute: Callable[[], Awaitable[ModelT]],
    *,
    ttl: int = TTL_SECONDS,
) -> ModelT:
    """Serve `compute()`'s answer for an immutable input `revision`; None computes live."""
    if revision is None:
        return await compute()
    key = _key(name, revision, params)
    cache = _cache_client()
    stored = await cache.get(key)
    if stored is not None:
        try:
            return model.model_validate(stored)
        except ValueError:
            logger.warning("Invalid cached CRM lease page %s", name)
    pending = _inflight.get(key)
    if pending is not None:
        try:
            return model.model_validate(await asyncio.shield(pending))
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
        except Exception:
            pass
        # The computation we waited for failed or its caller went away: answer ourselves.
        return await compute()
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        result = await compute()
    except BaseException as exc:
        future.set_exception(exc)
        # Waiters re-raise it; mark it retrieved so an unawaited future does not warn.
        future.exception()
        raise
    finally:
        _inflight.pop(key, None)
    payload = result.model_dump(mode="json")
    future.set_result(payload)
    await cache.set(key, payload, expire=ttl)
    return result
