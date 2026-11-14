"""Worker-local CRM admission; deployment must budget all workers and replicas."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.clickhouse.client import limit_queries
from app.config import settings


@dataclass
class _Tenant:
    slots: asyncio.Semaphore
    users: int = 0


@dataclass
class _Capacity:
    requests: asyncio.Semaphore
    queries: asyncio.Semaphore
    active: int = 0
    # Requests admitted or queued per tenant; a tenant leaves when its last one ends.
    organizations: dict[str, int] = field(default_factory=dict)
    tenants: dict[str, _Tenant] = field(default_factory=dict)


_capacity: _Capacity | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _current() -> _Capacity:
    global _capacity, _loop
    loop = asyncio.get_running_loop()
    if _capacity is None or _loop is not loop:
        _loop = loop
        _capacity = _Capacity(
            asyncio.Semaphore(settings.CRM_MAX_EXPENSIVE_REQUESTS),
            asyncio.Semaphore(settings.CRM_MAX_CONCURRENT_QUERIES),
        )
    return _capacity


@asynccontextmanager
async def expensive_crm(
    organization_id: str, *, before_wait: Callable[[], Awaitable[None]] | None = None
) -> AsyncIterator[None]:
    """Queue a request until the worker and its tenant have room, then bound its queries.

    A page loads several CRM panels at once, so a full budget waits (FIFO) instead of
    failing; the number of requests running at once, and so memory, stays the same.
    A tenant first takes one of its own slots and only then a worker slot, so one
    tenant's backlog never holds the worker slots another tenant is waiting for.
    ``before_wait`` runs once, only if the request has to queue (the router releases
    the idle database connection there). Waiting is bounded: past
    CRM_ADMISSION_WAIT_SECONDS the request is rejected before any work starts.
    """
    capacity = _current()
    tenant = capacity.tenants.get(organization_id)
    if tenant is None:
        tenant = _Tenant(asyncio.Semaphore(settings.CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG))
        capacity.tenants[organization_id] = tenant
    tenant.users += 1
    capacity.organizations[organization_id] = tenant.users
    admitted = False
    try:
        if before_wait is not None and (tenant.slots.locked() or capacity.requests.locked()):
            await before_wait()
        try:
            async with asyncio.timeout(settings.CRM_ADMISSION_WAIT_SECONDS):
                await tenant.slots.acquire()
                try:
                    await capacity.requests.acquire()
                except BaseException:
                    tenant.slots.release()
                    raise
        except TimeoutError:
            raise HTTPException(
                status_code=429,
                detail="CRM is busy. Retry this request shortly.",
                headers={"Retry-After": "2"},
            ) from None
        admitted = True
        capacity.active += 1
        with limit_queries(
            capacity.queries,
            max_memory_bytes=settings.CRM_QUERY_MAX_MEMORY_BYTES,
            max_threads=settings.CRM_QUERY_MAX_THREADS,
        ):
            yield
    finally:
        if admitted:
            capacity.active -= 1
            capacity.requests.release()
            tenant.slots.release()
        tenant.users -= 1
        if tenant.users:
            capacity.organizations[organization_id] = tenant.users
        else:
            del capacity.organizations[organization_id]
            del capacity.tenants[organization_id]
