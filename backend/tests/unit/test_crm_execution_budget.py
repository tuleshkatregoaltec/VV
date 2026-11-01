"""An abandoned page must not retain admission or multiply warehouse memory."""

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


async def test_overload_rejects_before_work_but_other_tenant_can_enter():
    async with execution.expensive_crm("org-a"):
        with pytest.raises(HTTPException) as rejected:
            async with execution.expensive_crm("org-a"):
                pytest.fail("overloaded tenant must never start work")
        assert rejected.value.status_code == 429
        assert rejected.value.headers == {"Retry-After": "2"}
        async with execution.expensive_crm("org-b"):
            with pytest.raises(HTTPException):
                async with execution.expensive_crm("org-c"):
                    pytest.fail("worker cannot admit an unbounded backlog")
    assert execution._capacity.active == 0
    assert execution._capacity.organizations == {}
    async with execution.expensive_crm("org-a"):
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
