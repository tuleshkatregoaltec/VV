"""CRM admission queues a page's burst instead of failing it, without raising the memory
budget: an abandoned page must not retain admission or multiply warehouse memory."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.clickhouse import client
from app.core.async_work import run_in_thread
from app.crm import execution


@pytest.fixture(autouse=True)
def budgets(monkeypatch):
    monkeypatch.setattr(execution, "_capacity", None)
    monkeypatch.setattr(execution, "_loop", None)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS", 2)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG", 1)
    monkeypatch.setattr(execution.settings, "CRM_MAX_CONCURRENT_QUERIES", 1)
    # Long enough for queued test work, short enough that a held slot fails fast.
    monkeypatch.setattr(execution.settings, "CRM_ADMISSION_WAIT_SECONDS", 0.2)


async def _burst(organizations, *, hold=0.01):
    """Run one admitted unit of work per entry; return peak overall and per-org activity."""
    active: dict[str, int] = {}
    peak = {"all": 0}

    async def work(org):
        async with execution.expensive_crm(org):
            active[org] = active.get(org, 0) + 1
            peak["all"] = max(peak["all"], sum(active.values()))
            peak[org] = max(peak.get(org, 0), active[org])
            await asyncio.sleep(hold)
            active[org] -= 1
        return org

    return await asyncio.gather(*(work(org) for org in organizations)), peak


async def test_page_burst_from_one_org_queues_and_all_complete_within_its_budget(monkeypatch):
    # The Owners page fires its panels together; every one must load, never 429.
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG", 2)
    done, peak = await _burst(["org-a"] * 5)
    assert done == ["org-a"] * 5
    # Memory safety is unchanged: no more work runs at once than the budget allows.
    assert peak["org-a"] == 2
    assert execution._capacity.active == 0
    assert execution._capacity.organizations == {}


async def test_busy_tenant_queue_does_not_block_another_tenant():
    order = []

    async def hold(org, seconds):
        async with execution.expensive_crm(org):
            order.append(org)
            await asyncio.sleep(seconds)

    # org-a has a backlog four deep (per-org budget 1); org-b arrives last.
    tasks = [asyncio.create_task(hold("org-a", 0.02)) for _ in range(4)]
    await asyncio.sleep(0)
    tasks.append(asyncio.create_task(hold("org-b", 0)))
    await asyncio.gather(*tasks)
    # org-b takes the free worker slot straight away instead of queueing behind org-a.
    assert order.index("org-b") == 1
    _, peak = await _burst(["org-a", "org-b", "org-c"] * 2)
    assert peak["all"] == 2


async def test_admission_wait_is_bounded_and_timed_out_work_never_starts():
    async with execution.expensive_crm("org-a"):
        with pytest.raises(HTTPException) as rejected:
            async with execution.expensive_crm("org-a"):
                pytest.fail("work that waited past the bound must never start")
        assert rejected.value.status_code == 429
        assert rejected.value.headers == {"Retry-After": "2"}
        assert execution._capacity.organizations == {"org-a": 1}
    assert execution._capacity.active == 0
    assert execution._capacity.organizations == {}
    async with execution.expensive_crm("org-a"):
        pass


async def test_cancelled_waiter_gives_up_its_place_without_leaking_capacity():
    async with execution.expensive_crm("org-a"):
        waiter = asyncio.create_task(execution.expensive_crm("org-a").__aenter__())
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    assert execution._capacity.active == 0
    assert execution._capacity.organizations == {}
    done, _ = await _burst(["org-a", "org-a"])
    assert done == ["org-a", "org-a"]


async def test_queued_request_releases_its_idle_database_connection_before_waiting():
    # Queued requests must not pin pool connections the admitted ones need.
    released = []

    async def release():
        released.append("released")

    async with execution.expensive_crm("org-a", before_wait=release):
        assert released == []  # a free slot is taken without touching the session
        waiter = asyncio.create_task(_enter_and_exit("org-a", release))
        await asyncio.sleep(0.01)
        assert released == ["released"]
    await waiter


async def _enter_and_exit(org, release):
    async with execution.expensive_crm(org, before_wait=release):
        pass


async def test_child_queries_share_one_worker_budget_and_settings_do_not_escape(monkeypatch):
    active = 0
    maximum = 0
    seen = []

    async def fake_query(sql, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(active, maximum)
        seen.append(kwargs["settings"])
        try:
            await asyncio.sleep(0.005)
            return SimpleNamespace(column_names=["ok"], result_rows=[(1,)])
        finally:
            active -= 1

    monkeypatch.setattr(
        client, "get_client", AsyncMock(return_value=SimpleNamespace(query=fake_query))
    )
    async with execution.expensive_crm("org-a"):
        assert (
            await asyncio.gather(*(client.query("SELECT 1") for _ in range(5))) == [[{"ok": 1}]] * 5
        )
    assert maximum == 1
    assert all(
        item["max_memory_usage"] == execution.settings.CRM_QUERY_MAX_MEMORY_BYTES for item in seen
    )
    assert all(item["max_threads"] == 2 and item["max_execution_time"] == 60 for item in seen)
    await client.query("SELECT 1")
    assert seen[-1] == {}


async def test_disconnect_awaits_child_cleanup_before_capacity_is_reusable(monkeypatch):
    started = asyncio.Event()
    cleaned = asyncio.Event()
    disconnected = asyncio.Event()
    killed = AsyncMock()
    monkeypatch.setattr(client, "kill_query_group", killed)

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    # run_cancellable's detector is asynchronous, matching Starlette Request.
    async def is_disconnected():
        return disconnected.is_set()

    async def guarded_run():
        async with execution.expensive_crm("org-a"):
            return await client.run_cancellable(is_disconnected, work(), poll_seconds=0.001)

    task = asyncio.create_task(guarded_run())
    await started.wait()
    disconnected.set()
    with pytest.raises(client.ClientDisconnected):
        await task
    assert cleaned.is_set()
    killed.assert_awaited_once()
    assert execution._capacity.active == 0
    assert client._query_limits.get() is None
    assert client._query_scope.get() is None


async def test_operation_exception_returns_its_admission_slot():
    with pytest.raises(ValueError):
        async with execution.expensive_crm("org-a"):
            raise ValueError("work failed")
    async with execution.expensive_crm("org-a"):
        assert execution._capacity.active == 1


async def test_cancelled_thread_keeps_admission_until_blocking_work_has_finished():
    started = threading.Event()
    finish = threading.Event()

    def blocking():
        started.set()
        finish.wait(timeout=2)

    async def admitted():
        async with execution.expensive_crm("org-a"):
            await run_in_thread(blocking)

    task = asyncio.create_task(admitted())
    try:
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        assert execution._capacity.active == 1
        task.cancel()
        await asyncio.sleep(0.005)
        assert execution._capacity.active == 1
    finally:
        finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert execution._capacity.active == 0


async def test_concurrent_owners_page_requests_from_one_org_all_succeed(client, monkeypatch):
    calls = 0

    async def slow_empty(*args, **kwargs):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.02)
        return []

    for name in ("list_contact_imports", "list_owner_workspaces", "list_inbound_imports"):
        monkeypatch.setattr("app.crm.router." + name, slow_empty)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG", 2)
    paths = ["contact-imports", "owner-workspaces", "inbound/imports"] * 2
    responses = await asyncio.gather(*(client.get("/api/v1/crm/" + p) for p in paths[:5]))
    assert [r.status_code for r in responses] == [200] * 5
    assert calls == 5


async def test_overloaded_authenticated_route_never_starts_warehouse_work(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router.list_renewal_areas", service)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG", 1)
    async with execution.expensive_crm("1"):
        response = await client.get("/api/v1/crm/renewal-areas")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "2"
    service.assert_not_awaited()


@pytest.mark.parametrize(
    "path, service_name",
    [
        ("/api/v1/crm/contact-imports/1/owner-summary", "get_owner_history_summary"),
        ("/api/v1/crm/contact-lists", "list_contact_lists"),
        ("/api/v1/crm/leads/test/contacts", "list_lead_imported_contacts"),
        ("/api/v1/crm/inbound/enquiries", "list_inbound_enquiries"),
    ],
)
async def test_aliases_cannot_bypass_shared_admission(client, monkeypatch, path, service_name):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router." + service_name, service)
    async with execution.expensive_crm("1"):
        response = await client.get(path)
    assert response.status_code == 429
    service.assert_not_awaited()


@pytest.mark.parametrize(
    "in_transaction, pending, committed",
    [(True, False, True), (True, True, False), (False, False, False)],
)
async def test_router_releases_only_a_clean_authentication_transaction(
    in_transaction, pending, committed
):
    from app.crm.router import _release_idle_connection

    db = SimpleNamespace(
        in_transaction=lambda: in_transaction,
        new={"row"} if pending else set(),
        dirty=set(),
        deleted=set(),
        commit=AsyncMock(),
    )
    await _release_idle_connection(db)
    # Ending a read-only auth transaction frees the pool connection; the next query
    # starts a new transaction whose begin hook re-applies the actor context.
    assert db.commit.await_count == (1 if committed else 0)
