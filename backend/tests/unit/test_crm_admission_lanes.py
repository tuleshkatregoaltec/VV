"""Cheap CRM reads must not queue behind warehouse-heavy pages, while heavy work stays bounded.

Live (one worker, CRM_MAX_EXPENSIVE_REQUESTS=1 and _PER_ORG=1) the Inbox list took 0.6 s alone
and 15.3 s behind the dashboard, because every CRM route shared one admission slot.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.routing import APIRoute

from app.clickhouse import client as clickhouse
from app.crm import execution, router


@pytest.fixture(autouse=True)
def budgets(monkeypatch):
    monkeypatch.setattr(execution, "_capacity", None)
    monkeypatch.setattr(execution, "_loop", None)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS", 1)
    monkeypatch.setattr(execution.settings, "CRM_MAX_EXPENSIVE_REQUESTS_PER_ORG", 1)
    monkeypatch.setattr(execution.settings, "CRM_MAX_CONCURRENT_QUERIES", 1)
    monkeypatch.setattr(execution.settings, "CRM_ADMISSION_WAIT_SECONDS", 0.2)


def _lanes(route: APIRoute) -> set[str]:
    calls = {dependency.call for dependency in route.dependant.dependencies}
    return {
        name
        for name, call in (("expensive", router._expensive_crm), ("light", router._light_crm))
        if call in calls
    }


LIGHT_ROUTES = {
    ("GET", "/api/v1/crm/inbound/enquiries"),
    ("POST", "/api/v1/crm/inbound/enquiries"),
    ("GET", "/api/v1/crm/inbound/enquiries/{enquiry_id}"),
    ("PATCH", "/api/v1/crm/inbound/enquiries/{enquiry_id}"),
    ("POST", "/api/v1/crm/inbound/enquiries/{enquiry_id}/notes"),
    ("POST", "/api/v1/crm/inbound/enquiries/{enquiry_id}/activities"),
    ("PATCH", "/api/v1/crm/inbound/matches/{match_id}"),
    ("GET", "/api/v1/crm/inbound/imports"),
    ("GET", "/api/v1/crm/contact-imports"),
    ("GET", "/api/v1/crm/contact-lists"),
    ("GET", "/api/v1/crm/owner-workspaces"),
    ("PATCH", "/api/v1/crm/owner-workspaces/bulk"),
    ("GET", "/api/v1/crm/area-preferences"),
    ("PUT", "/api/v1/crm/area-preferences"),
    ("GET", "/api/v1/crm/workspaces"),
    ("GET", "/api/v1/crm/workspaces/{lead_id}"),
    ("PATCH", "/api/v1/crm/workspaces/{lead_id}"),
    ("POST", "/api/v1/crm/workspaces/{lead_id}/notes"),
    ("DELETE", "/api/v1/crm/notes/{note_id}"),
    ("GET", "/api/v1/crm/saved-leads"),
    ("DELETE", "/api/v1/crm/saved-leads/{saved_id}"),
}


def test_every_crm_route_declares_exactly_one_admission_lane():
    routes = [route for route in router.router.routes if isinstance(route, APIRoute)]
    assert routes
    for route in routes:
        assert len(_lanes(route)) == 1, (route.methods, route.path)
    light = {
        (method, route.path)
        for route in routes
        if _lanes(route) == {"light"}
        for method in route.methods
    }
    # New routes default to the bounded expensive lane; only reviewed cheap reads are light.
    assert light == LIGHT_ROUTES


def test_the_router_itself_no_longer_gates_every_route():
    calls = {dependency.dependency for dependency in router.router.dependencies}
    assert router._expensive_crm not in calls


@pytest.mark.parametrize(
    "path, service_name",
    [
        ("/api/v1/crm/inbound/enquiries", "list_inbound_enquiries"),
        ("/api/v1/crm/inbound/imports", "list_inbound_imports"),
        ("/api/v1/crm/contact-imports", "list_contact_imports"),
        ("/api/v1/crm/owner-workspaces", "list_owner_workspaces"),
        ("/api/v1/crm/workspaces", "list_lead_workspaces"),
        ("/api/v1/crm/saved-leads", "list_saved_leads"),
        ("/api/v1/crm/area-preferences", "get_area_preferences"),
    ],
)
async def test_cheap_reads_answer_while_the_dashboard_holds_the_only_slot(
    client, monkeypatch, path, service_name
):
    service = AsyncMock(return_value=[])
    if service_name == "list_inbound_enquiries":
        service.return_value = {"enquiries": [], "total": 0, "summary": {}}
    if service_name == "get_area_preferences":
        service.return_value = {"areas": []}
    if service_name == "list_lead_workspaces":
        service.return_value = {"items": [], "total": 0, "limit": 100, "offset": 0}
    monkeypatch.setattr("app.crm.router." + service_name, service)
    async with execution.expensive_crm("1"):
        response = await client.get(path)
    assert response.status_code == 200, response.text
    service.assert_awaited_once()


@pytest.mark.parametrize(
    "path, service_name",
    [
        ("/api/v1/crm/dashboard", "get_dashboard"),
        ("/api/v1/crm/renewal-leads", "list_renewal_leads"),
        ("/api/v1/crm/owner-registry", "get_owner_registry"),
        ("/api/v1/crm/leads/x/report", "get_property_report"),
    ],
)
async def test_heavy_pages_still_queue_behind_the_slot(client, monkeypatch, path, service_name):
    service = AsyncMock()
    monkeypatch.setattr("app.crm.router." + service_name, service)
    async with execution.expensive_crm("1"):
        response = await client.get(path)
    assert response.status_code == 429
    service.assert_not_awaited()


async def test_light_lane_bounds_its_warehouse_queries_separately(monkeypatch):
    seen = []
    active = maximum = 0

    async def fake_query(sql, **kwargs):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        seen.append(kwargs["settings"])
        try:
            await asyncio.sleep(0.005)
            return SimpleNamespace(column_names=["ok"], result_rows=[(1,)])
        finally:
            active -= 1

    monkeypatch.setattr(
        clickhouse, "get_client", AsyncMock(return_value=SimpleNamespace(query=fake_query))
    )
    holding = asyncio.Event()
    release = asyncio.Event()

    async def heavy():
        async with execution.expensive_crm("1"):
            holding.set()
            await release.wait()

    task = asyncio.create_task(heavy())
    await holding.wait()
    try:
        async with execution.light_crm("1"):
            # Not admitted through the expensive slot the dashboard holds, yet bounded.
            assert await asyncio.gather(*(clickhouse.query("SELECT 1") for _ in range(3)))
    finally:
        release.set()
        await task
    assert maximum == 1
    assert all(
        item["max_memory_usage"] == execution.LIGHT_QUERY_MAX_MEMORY_BYTES
        and item["max_memory_usage"] <= execution.settings.CRM_QUERY_MAX_MEMORY_BYTES
        and item["max_execution_time"] <= 60
        for item in seen
    )


async def test_heavy_section_from_a_light_request_takes_the_expensive_slot():
    async with execution.light_crm("1"):
        async with execution.heavy_section("1"):
            assert execution._capacity.active == 1
        assert execution._capacity.active == 0


async def test_heavy_section_waits_for_the_slot_and_is_bounded():
    holding = asyncio.Event()
    release = asyncio.Event()

    async def dashboard():
        async with execution.expensive_crm("1"):
            holding.set()
            await release.wait()

    task = asyncio.create_task(dashboard())
    await holding.wait()
    try:
        with pytest.raises(Exception) as caught:
            await _light_then_heavy()
    finally:
        release.set()
        await task
    assert getattr(caught.value, "status_code", None) == 429


async def _light_then_heavy():
    async with execution.light_crm("1"):
        async with execution.heavy_section("1"):
            return True


async def test_heavy_section_inside_an_admitted_request_is_reentrant():
    # Per-org budget 1: re-acquiring would deadlock until the admission timeout.
    async with execution.expensive_crm("1"):
        async with execution.heavy_section("1"):
            assert execution._capacity.active == 1


async def test_uncached_scoped_owner_assessment_from_a_light_request_is_admitted(monkeypatch):
    from app.crm import owner_assessment, owner_queries

    observed = []

    async def loader(*args, **kwargs):
        observed.append(execution._capacity.active)
        return []

    monkeypatch.setattr(owner_assessment, "_scoped_recent", {})
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="rev"))
    monkeypatch.setattr(
        owner_assessment.owner_repository, "owner_sources_only", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(owner_assessment.owner_repository, "list_owner_history_rows", loader)
    monkeypatch.setattr(
        owner_queries, "fetch_assessment_source_fingerprint", AsyncMock(return_value="wh")
    )
    async with execution.light_crm("org"):
        await owner_assessment.get_owner_assessment(
            None, organization_id="org", unit_candidate_keys=["unit-a"]
        )
        # The cached scope is served without taking a slot.
        await owner_assessment.get_owner_assessment(
            None, organization_id="org", unit_candidate_keys=["unit-a"]
        )
    assert observed == [1]
    assert execution._capacity.active == 0


async def test_uncached_whole_org_assessment_from_a_light_request_is_admitted(monkeypatch):
    from app.crm import owner_assessment

    observed = []
    snapshot = owner_assessment._project([], owner_assessment.datetime.now(), "available")

    async def build(*args, **kwargs):
        observed.append(execution._capacity.active)
        return snapshot

    cache = SimpleNamespace(get=AsyncMock(return_value=None), set=AsyncMock())
    monkeypatch.setattr(owner_assessment, "_recent", None)
    monkeypatch.setattr(owner_assessment, "_cache_client", lambda: cache)
    monkeypatch.setattr(owner_assessment, "_source_revision", AsyncMock(return_value="rev"))
    monkeypatch.setattr(
        owner_assessment.owner_repository, "owner_sources_only", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(owner_assessment, "_build", build)
    monkeypatch.setattr(owner_assessment, "run_in_thread", AsyncMock(return_value="{}"))
    async with execution.light_crm("org"):
        await owner_assessment.get_owner_assessment(None, organization_id="org")
    assert observed == [1]


async def test_workspaces_are_paged_with_a_default_and_a_maximum(client, monkeypatch):
    service = AsyncMock(return_value={"items": [], "total": 4_745, "limit": 100, "offset": 0})
    monkeypatch.setattr("app.crm.router.list_lead_workspaces", service)

    first = await client.get("/api/v1/crm/workspaces")
    assert first.status_code == 200, first.text
    assert first.json()["total"] == 4_745
    assert (service.await_args.kwargs["limit"], service.await_args.kwargs["offset"]) == (100, 0)

    await client.get("/api/v1/crm/workspaces?limit=500&offset=1000")
    assert (service.await_args.kwargs["limit"], service.await_args.kwargs["offset"]) == (500, 1000)

    for bad in ("limit=501", "limit=0", "offset=-1"):
        assert (await client.get(f"/api/v1/crm/workspaces?{bad}")).status_code == 422
