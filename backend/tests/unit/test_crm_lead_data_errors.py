"""Lease-data failures say what happened instead of one generic 503 or an empty success.

Live, any ClickHouse error became 503 "temporarily unavailable" and missing lease tables
returned an empty 200, so a page could show "no leads" when the data was simply not there.
"""

from datetime import date
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.crm import lead_cache, opportunities, opportunity_queries, renewal_leads


class DatabaseError(Exception):
    pass


MEMORY = DatabaseError(
    "Code: 241. DB::Exception: Memory limit (for query) exceeded: would use 3.00 GiB. "
    "(MEMORY_LIMIT_EXCEEDED)"
)
TIMEOUT = DatabaseError(
    "Code: 159. DB::Exception: Timeout exceeded: elapsed 60 s. (TIMEOUT_EXCEEDED)"
)
BROKEN = DatabaseError("Code: 47. DB::Exception: Missing columns: 'x'. (UNKNOWN_IDENTIFIER)")

ANCHOR = date(2026, 11, 15)


def _dashboard():
    return opportunities.get_dashboard(
        status=None,
        priority=None,
        asset_class=None,
        property_type=None,
        area=None,
        project=None,
        building=None,
        search=None,
        breakdown="area",
        limit=50,
        offset=0,
        as_of=ANCHOR,
    )


def _renewals():
    return renewal_leads.list_renewals(
        window=None,
        area=None,
        property_type=None,
        project=None,
        building=None,
        limit=50,
        offset=0,
        as_of=ANCHOR,
    )


PAGES = {
    "dashboard": (_dashboard, "fetch_dashboard"),
    "renewals": (_renewals, "fetch_renewals"),
    "renewal_areas": (
        lambda: renewal_leads.list_renewal_areas(as_of=ANCHOR),
        "fetch_renewal_areas",
    ),
}


@pytest.fixture(autouse=True)
def live(monkeypatch):
    monkeypatch.setattr(lead_cache, "lead_data_revision", AsyncMock(return_value=None))
    monkeypatch.setattr(opportunity_queries, "_tables_exist", AsyncMock(return_value=True))
    monkeypatch.setattr(opportunities, "_tables_exist", opportunity_queries._tables_exist)


@pytest.mark.parametrize("page", PAGES)
@pytest.mark.parametrize("error", [MEMORY, TIMEOUT, TimeoutError("read timed out")])
async def test_an_overloaded_warehouse_is_a_retryable_busy_error(monkeypatch, page, error):
    view, fetch = PAGES[page]
    monkeypatch.setattr(opportunity_queries, fetch, AsyncMock(side_effect=error))
    with pytest.raises(HTTPException) as caught:
        await view()
    assert caught.value.status_code == 503
    assert caught.value.headers["Retry-After"]
    assert "busy" in caught.value.detail


@pytest.mark.parametrize("page", PAGES)
async def test_another_failure_is_unavailable_without_a_retry_hint(monkeypatch, page):
    view, fetch = PAGES[page]
    monkeypatch.setattr(opportunity_queries, fetch, AsyncMock(side_effect=BROKEN))
    with pytest.raises(HTTPException) as caught:
        await view()
    assert caught.value.status_code == 503
    assert not (caught.value.headers or {}).get("Retry-After")
    assert "unavailable" in caught.value.detail


@pytest.mark.parametrize("page", [*PAGES, "detail"])
async def test_missing_lease_tables_are_not_an_empty_success(monkeypatch, page):
    monkeypatch.setattr(opportunity_queries, "_tables_exist", AsyncMock(return_value=False))
    monkeypatch.setattr(opportunities, "_tables_exist", opportunity_queries._tables_exist)
    view = (
        (lambda: opportunities.get_lead_detail("e1", as_of=ANCHOR))
        if page == "detail"
        else PAGES[page][0]
    )
    with pytest.raises(HTTPException) as caught:
        await view()
    assert caught.value.status_code == 503
    assert "not loaded" in caught.value.detail


async def test_missing_tables_for_the_feed_are_reported_too(monkeypatch):
    monkeypatch.setattr(opportunity_queries, "_tables_exist", AsyncMock(return_value=False))
    monkeypatch.setattr(
        renewal_leads,
        "get_area_preferences",
        AsyncMock(return_value=renewal_leads.CrmAreaPreferencesResponse(areas=["Al Barsha"])),
    )
    with pytest.raises(HTTPException) as caught:
        await renewal_leads.list_renewal_leads(
            None, user_id="u", organization_id="o", limit=10, offset=0, as_of=ANCHOR
        )
    assert caught.value.status_code == 503
    assert "not loaded" in caught.value.detail
