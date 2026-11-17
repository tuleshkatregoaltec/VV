"""Warehouse-wide CRM pages are cached per data release, so only the first view after a load pays.

Live, /dashboard took ~15 s on every view (five full-ranking queries, 13.5M rows), even with an
area filter that matches nothing, and nothing was cached.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel

from app.crm import lead_cache


class Page(BaseModel):
    value: int


class FakeRedis:
    def __init__(self):
        self.store: dict[str, object] = {}
        self.expiry: dict[str, int] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expire=None):
        self.store[key] = value
        self.expiry[key] = expire


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(lead_cache, "_cache_client", lambda: fake)
    monkeypatch.setattr(lead_cache, "_inflight", {})
    return fake


def _revision(monkeypatch, *values):
    sequence = iter(values)
    monkeypatch.setattr(
        lead_cache, "lead_data_revision", AsyncMock(side_effect=lambda: next(sequence))
    )


async def test_a_second_view_of_the_same_release_is_served_from_the_cache(monkeypatch, redis):
    _revision(monkeypatch, "r1", "r1")
    compute = AsyncMock(return_value=Page(value=7))
    first = await lead_cache.cached("dashboard", {"area": None}, Page, compute)
    second = await lead_cache.cached("dashboard", {"area": None}, Page, compute)
    assert first == second == Page(value=7)
    assert compute.await_count == 1
    assert all(0 < ttl <= lead_cache.TTL_SECONDS for ttl in redis.expiry.values())


async def test_a_new_data_release_recomputes(monkeypatch, redis):
    # A vv-dxbi-sync load changes the sources' parts, so the revision and key change.
    _revision(monkeypatch, "r1", "r2")
    compute = AsyncMock(side_effect=[Page(value=1), Page(value=2)])
    assert (await lead_cache.cached("dashboard", {}, Page, compute)).value == 1
    assert (await lead_cache.cached("dashboard", {}, Page, compute)).value == 2


async def test_parameters_are_part_of_the_key(monkeypatch, redis):
    _revision(monkeypatch, "r1", "r1")
    compute = AsyncMock(side_effect=[Page(value=1), Page(value=2)])
    await lead_cache.cached("dashboard", {"area": "A"}, Page, compute)
    await lead_cache.cached("dashboard", {"area": "B"}, Page, compute)
    assert compute.await_count == 2


async def test_an_unknown_or_moving_release_is_computed_live_and_not_stored(monkeypatch, redis):
    # A running mutation or missing metadata: never pin an answer to an unknown release.
    _revision(monkeypatch, None, None)
    compute = AsyncMock(side_effect=[Page(value=1), Page(value=2)])
    assert (await lead_cache.cached("dashboard", {}, Page, compute)).value == 1
    assert (await lead_cache.cached("dashboard", {}, Page, compute)).value == 2
    assert redis.store == {}


async def test_concurrent_identical_views_compute_once(monkeypatch, redis):
    monkeypatch.setattr(lead_cache, "lead_data_revision", AsyncMock(return_value="r1"))
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return Page(value=3)

    tasks = [
        asyncio.create_task(lead_cache.cached("dashboard", {}, Page, compute)) for _ in range(3)
    ]
    await started.wait()
    release.set()
    assert await asyncio.wait_for(asyncio.gather(*tasks), 1) == [Page(value=3)] * 3
    assert calls == 1


async def test_a_failed_compute_is_not_cached(monkeypatch, redis):
    _revision(monkeypatch, "r1", "r1")
    compute = AsyncMock(side_effect=[RuntimeError("boom"), Page(value=5)])
    with pytest.raises(RuntimeError):
        await lead_cache.cached("dashboard", {}, Page, compute)
    assert (await lead_cache.cached("dashboard", {}, Page, compute)).value == 5


async def test_revision_is_none_while_a_source_mutation_runs(monkeypatch):
    from crm_rental_sql import DEPENDENCIES, VIEW_DEPENDENCIES

    rows = [
        {
            "name": name,
            "engine": "View" if name in VIEW_DEPENDENCIES else "ReplacingMergeTree",
            "uuid": "u",
            "ddl": "d",
            "parts": "[]",
            "pending": 1 if name == "dxbi_rental_events" else 0,
        }
        for name in DEPENDENCIES
    ]
    monkeypatch.setattr(lead_cache, "query", AsyncMock(return_value=rows))
    assert await lead_cache.lead_data_revision() is None
    rows[0]["pending"] = 0
    for row in rows:
        row["pending"] = 0
    first = await lead_cache.lead_data_revision()
    rows[1]["parts"] = '[["all_1_1_0", 10]]'
    assert first and await lead_cache.lead_data_revision() not in {None, first}


async def test_a_waiter_whose_leader_fails_computes_its_own_answer(monkeypatch, redis):
    monkeypatch.setattr(lead_cache, "lead_data_revision", AsyncMock(return_value="r1"))
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def compute():
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            raise RuntimeError("query killed: the first agent left")
        return Page(value=9)

    leader = asyncio.create_task(lead_cache.cached("dashboard", {}, Page, compute))
    await started.wait()
    waiter = asyncio.create_task(lead_cache.cached("dashboard", {}, Page, compute))
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(RuntimeError):
        await leader
    assert await waiter == Page(value=9)


@pytest.mark.parametrize("page", ["dashboard", "renewals", "renewal_areas"])
async def test_lease_pages_compute_once_per_release(monkeypatch, redis, page):
    from datetime import date

    from app.crm import opportunities, opportunity_queries, renewal_leads

    monkeypatch.setattr(lead_cache, "lead_data_revision", AsyncMock(return_value="r1"))
    monkeypatch.setattr(opportunity_queries, "_tables_exist", AsyncMock(return_value=True))
    monkeypatch.setattr(opportunities, "_tables_exist", AsyncMock(return_value=True))
    empty_dashboard = ([], [{}], [], [], [{}])
    dashboard = AsyncMock(return_value=empty_dashboard)
    renewals = AsyncMock(return_value=([], 0, {}))
    areas = AsyncMock(return_value=[{"area": "Al Barsha", "upcoming_90_days": 3}])
    monkeypatch.setattr(opportunity_queries, "fetch_dashboard", dashboard)
    monkeypatch.setattr(opportunity_queries, "fetch_renewals", renewals)
    monkeypatch.setattr(opportunity_queries, "fetch_renewal_areas", areas)
    anchor = date(2026, 11, 15)

    async def view():
        if page == "dashboard":
            return await opportunities.get_dashboard(
                status=None,
                priority=None,
                asset_class=None,
                property_type=None,
                area="Al Barsha",
                project=None,
                building=None,
                search=None,
                breakdown="area",
                limit=50,
                offset=0,
                as_of=anchor,
            )
        if page == "renewals":
            return await renewal_leads.list_renewals(
                window=None,
                area=None,
                property_type=None,
                project=None,
                building=None,
                limit=50,
                offset=0,
                as_of=anchor,
            )
        return await renewal_leads.list_renewal_areas(as_of=anchor)

    first = await view()
    second = await view()
    assert first == second
    fetched = {"dashboard": dashboard, "renewals": renewals, "renewal_areas": areas}[page]
    assert fetched.await_count == 1
