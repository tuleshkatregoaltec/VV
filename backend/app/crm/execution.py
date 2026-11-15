"""Worker-local CRM admission; deployment must budget all workers and replicas.

Two lanes. The expensive lane admits a bounded number of warehouse-heavy requests per worker and
per tenant (the lead CTE, owner registry, imports, reports); memory stays bounded because only
that many run at once. The light lane is for Postgres reads and writes: it takes no admission
slot, so the Inbox never waits behind the dashboard, yet any ClickHouse query it happens to run
is serialised on its own semaphore with a smaller memory and time cap. Work a light request may
reach that is heavy only sometimes (an uncached owner assessment build) enters ``heavy_section``
and is admitted like an expensive request at that point.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import HTTPException

from app.clickhouse.client import limit_queries
from app.config import settings


@dataclass
class _Tenant:
    slots: asyncio.Semaphore
    users: int = 0


# A light request's incidental warehouse queries (a fingerprint, a lead key) are small; one
# that needs more than this is not light and fails instead of competing with the heavy lane.
LIGHT_QUERY_MAX_MEMORY_BYTES = 1_073_741_824

# The tenant whose expensive admission the current task holds, so nested heavy work re-enters.
_admitted: ContextVar[str | None] = ContextVar("crm_admitted_organization", default=None)


@dataclass
class _Capacity:
    requests: asyncio.Semaphore
    queries: asyncio.Semaphore
    light_queries: asyncio.Semaphore
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
        token = _admitted.set(organization_id)
        try:
            with limit_queries(
                capacity.queries,
                max_memory_bytes=settings.CRM_QUERY_MAX_MEMORY_BYTES,
                max_threads=settings.CRM_QUERY_MAX_THREADS,
            ):
                yield
        finally:
            _admitted.reset(token)
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


@asynccontextmanager
async def light_crm(organization_id: str) -> AsyncIterator[None]:
    """Run a cheap CRM request without an admission slot; its warehouse queries stay bounded."""
    del organization_id  # Light work is not budgeted per tenant; heavy sections are.
    capacity = _current()
    with limit_queries(
        capacity.light_queries,
        max_memory_bytes=min(LIGHT_QUERY_MAX_MEMORY_BYTES, settings.CRM_QUERY_MAX_MEMORY_BYTES),
        max_threads=settings.CRM_QUERY_MAX_THREADS,
    ):
        yield


@asynccontextmanager
async def heavy_section(organization_id: str) -> AsyncIterator[None]:
    """Admit heavy work reached from any request; a no-op when the request is already admitted.

    Acquire it before any lock the heavy work takes, the same order an expensive request uses
    (slot first, then lock), so a light and an expensive request never wait on each other.
    """
    if _admitted.get() is not None:
        yield
        return
    async with expensive_crm(organization_id):
        yield
