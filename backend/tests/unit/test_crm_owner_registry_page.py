"""The Owners list stays small and is not recomputed on every view.

Live, limit=100 returned 1.6 MB and limit=500 4.1 MB (one owner's properties alone ~50 KB), and
even limit=1 took 2.3 s because each view re-ranked all 178,793 owners.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_crm_owner_role_and_dld_unit import _property

from app.crm import lead_cache, owners
from app.crm.import_models import CrmOwnerProfile


def _profile(key: str, count: int) -> CrmOwnerProfile:
    return CrmOwnerProfile(
        owner_key=key,
        contact_name=key,
        highest_ownership_status="former_owner",
        highest_confidence_score=100,
        property_count=count,
        rental_linked_count=0,
        contact_ready_count=0,
        annual_rent_aed=0,
        properties=[_property(property_key=f"{key}-{i}") for i in range(count)],
    )


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, expire=None):
        self.store[key] = value


@pytest.fixture
def store(monkeypatch):
    profiles = {"big": _profile("big", 300), "small": _profile("small", 2)}
    reader = SimpleNamespace(
        state=SimpleNamespace(generation=9, source_audit={}),
        registry_page=AsyncMock(
            return_value=(
                ["big", "small"],
                2,
                {
                    "rental_owner_profiles": 0,
                    "registry_owner_profiles": 0,
                    "prior_owner_profiles": 2,
                    "needs_review_profiles": 0,
                    "multi_property_owners": 2,
                    "unfiled_profiles": 0,
                    "folder_overlap": 0,
                },
            )
        ),
        profiles=AsyncMock(return_value=profiles),
    )
    monkeypatch.setattr(owners, "open_store", AsyncMock(return_value=reader))
    redis = FakeRedis()
    monkeypatch.setattr(lead_cache, "_cache_client", lambda: redis)
    monkeypatch.setattr(lead_cache, "_inflight", {})
    return reader


async def _page(**overrides):
    args = dict(
        organization_id="org",
        list_id=None,
        scope="all",
        status=None,
        search=None,
        lease_window=None,
        portfolio_only=False,
        min_rent_aed=None,
        max_rent_aed=None,
        min_value_aed=None,
        max_value_aed=None,
        limit=100,
        offset=0,
    )
    args.update(overrides)
    return await owners.get_owner_registry(None, **args)


async def test_a_list_row_carries_a_bounded_slice_of_an_owners_properties(store):
    page = await _page()
    big, small = page.owners
    assert len(big.properties) == owners.OWNER_LIST_PROPERTIES_MAX
    assert big.properties_truncated is True
    assert big.property_count == 300  # the real count is kept for the row and filters
    assert len(small.properties) == 2 and small.properties_truncated is False


async def test_a_repeat_view_of_one_generation_is_served_from_the_cache(store):
    first = await _page(limit=1)
    second = await _page(limit=1)
    assert first == second
    assert store.registry_page.await_count == 1
    store.state.generation = 10  # a rebuilt assessment publishes a new generation
    await _page(limit=1)
    assert store.registry_page.await_count == 2


async def test_the_day_is_part_of_the_key(store, monkeypatch):
    await _page()
    monkeypatch.setattr(owners, "_today", lambda: date(2030, 1, 1))
    await _page()
    assert store.registry_page.await_count == 2
