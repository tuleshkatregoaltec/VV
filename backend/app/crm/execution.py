"""Worker-local CRM admission; deployment must budget all workers and replicas."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.clickhouse.client import limit_queries
from app.config import settings


@dataclass
class _Capacity:
    queries: asyncio.Semaphore
    active: int = 0
    organizations: dict[str, int] = field(default_factory=dict)


_capacity: _Capacity | None = None
_loop: asyncio.AbstractEventLoop | None = None


@asynccontextmanager
async def expensive_crm(organization_id: str) -> AsyncIterator[None]:
    """Reject overload before starting work, and bound every child warehouse query."""
    global _capacity, _loop
    loop = asyncio.get_running_loop()
    if _capacity is None or _loop is not loop:
        _loop = loop
        _capacity = _Capacity(asyncio.Semaphore(settings.CRM_MAX_CONCURRENT_QUERIES))
    capacity = _capacity
    tenant_active = capacity.organizations.get(organization_id, 0)
    # No await between checking and claiming: admission is atomic on the worker loop.
    if (
        capacity.active >= settings.CRM_MAX_EXPENSIVE_REQUESTS
        or tenant_active >= settings.CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG
    ):
        raise HTTPException(
            status_code=429,
            detail="CRM is busy. Retry this request shortly.",
            headers={"Retry-After": "2"},
        )
    capacity.active += 1
    capacity.organizations[organization_id] = tenant_active + 1
    try:
        with limit_queries(
            capacity.queries,
            max_memory_bytes=settings.CRM_QUERY_MAX_MEMORY_BYTES,
            max_threads=settings.CRM_QUERY_MAX_THREADS,
        ):
            yield
    finally:
        capacity.active -= 1
        remaining = capacity.organizations[organization_id] - 1
        if remaining:
            capacity.organizations[organization_id] = remaining
        else:
            del capacity.organizations[organization_id]
