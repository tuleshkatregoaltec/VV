from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.analytics import assistant
from app.analytics.assistant_models import ComparableRequest
from app.listings import assistant as listing_assistant
from app.listings.models import ListingCardResponse, ListingListResponse
from app.project import assistant as project_assistant
from app.supply.models import SupplyCatalogueProjectDetailResponse, SupplyCatalogueProjectsResponse


async def test_comparable_yield_and_small_sample_abstention_are_deterministic(monkeypatch):
    release = {
        "release_id": "r",
        "data_from": "2026-09-01",
        "data_to": "2026-09-30",
        "coverage": {"ranges": [{"from": "2026-09-01", "to": "2026-09-30", "status": "verified"}]},
    }
    monkeypatch.setattr(assistant.queries, "fetch_release", AsyncMock(return_value=release))
    monkeypatch.setattr(assistant.queries, "fetch_release_id", AsyncMock(return_value="r"))
    summary = {
        "count": 10,
        "rated_count": 10,
        "median_aed": 100000,
        "p25_aed": 90000,
        "p75_aed": 110000,
        "median_aed_per_sqft": 100,
    }
    read = AsyncMock(return_value=(summary, [{"amount_aed": 100000}]))
    monkeypatch.setattr(assistant.queries, "fetch_comparable_evidence", read)
    request = ComparableRequest(
        dataset="rentals",
        location="JVC",
        building="Tower",
        bedrooms="1",
        period={"type": "month", "month": "2026-09"},
        target_size_sqft=1000,
        asking_price_aed=1000000,
    )
    result = await assistant.get_comparable_evidence(request)
    assert result["gross_yield_pct"] == 10 and result["indicative_value_aed"] == 100000
    assert result["matching_count"] == 10 and result["sample_count"] == 1
    assert read.await_args.kwargs["size_min"] == 800 and read.await_args.kwargs["size_max"] == 1200
    summary["count"] = 4
    result = await assistant.get_comparable_evidence(request)
    assert result["gross_yield_pct"] is None and result["indicative_value_aed"] is None


async def test_listing_shortlist_never_includes_parties_or_links_and_normalizes_units(monkeypatch):
    card = ListingCardResponse(
        listing_id="internal",
        listing_mode="rent",
        asset_class="residential",
        title="Two bed",
        price_value=10000,
        price_period="monthly",
        size_value=1000,
        size_unit="sqft",
        agent_name="Private party",
        share_url="https://example.test",
        captured_at=datetime(2026, 10, 1, tzinfo=UTC),
        listing_age_days=100,
    )
    read = AsyncMock(return_value=ListingListResponse(listings=[card], total=30, limit=1, offset=0))
    monkeypatch.setattr(listing_assistant.service, "list_listings_from_clickhouse", read)
    result = await listing_assistant.research_listings(
        listing_assistant.ListingResearchRequest(
            mode="rent", location="JVC", min_age_days=91, limit=1
        )
    )
    row = result["records"][0]
    assert row["asking_aed"] == 120000 and row["price_per_sqft_aed"] == 120
    assert not {"agent_name", "share_url", "listing_id"} & row.keys()
    assert result["total"] == 30 and result["returned_count"] == 1
    assert read.await_args.kwargs["min_age_days"] == 91


async def test_project_comparison_reports_missing_fields_and_excludes_assets(monkeypatch):
    project = SupplyCatalogueProjectDetailResponse(
        project_id=1,
        project_name="Tower",
        developer_name="Builder",
        payment_plan=[{"label": "Handover", "percent": "50"}],
        source_metadata={"scraped_at": "2026-09-30", "source_run_id": "private"},
    )
    monkeypatch.setattr(
        project_assistant.supply_service,
        "list_supply_catalogue_projects",
        AsyncMock(
            return_value=SupplyCatalogueProjectsResponse(
                projects=[project], total=1, limit=5, offset=0
            )
        ),
    )
    monkeypatch.setattr(
        project_assistant.supply_service,
        "get_supply_catalogue_project",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(
        project_assistant.service,
        "get_project_details",
        AsyncMock(return_value=SimpleNamespace(percent_completed=0)),
    )
    result = await project_assistant.compare_stored_projects(["Tower"])
    item = result["projects"][0]
    assert item["construction_progress_pct"] == 0
    assert "construction progress" not in item["missing_information"]
    assert item["payment_plan"][0]["percent"] == "50"
    assert "unit prices and sizes" in item["missing_information"]
    assert not {"brochures", "gallery", "source_metadata"} & item.keys()


@pytest.mark.parametrize(
    "fields", [{"limit": 21}, {"min_age_days": -1}, {"min_age_days": 90, "max_age_days": 10}]
)
def test_listing_research_cannot_expand_scope_or_bounds(fields):
    with pytest.raises(ValidationError):
        listing_assistant.ListingResearchRequest(location="JVC", **fields)
