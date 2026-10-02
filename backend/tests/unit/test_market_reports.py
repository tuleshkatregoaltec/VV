"""Report components retain domain facts, bindings, periods and shared-release authority."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.market import reports
from app.market.evidence import MarketAccessContext, MarketRelease, use_market_release

CONTEXT = MarketAccessContext("u", "o", date(2026, 10, 3), "t")


@pytest.fixture
def domains(monkeypatch):
    values = {"median_aed": 80000, "p25_aed": 70000, "p75_aed": 90000}
    metrics = AsyncMock(
        return_value={
            "coverage": {"status": "complete"},
            "total": {"count": 5, "values": values},
            "rows": [{"group": "New", "count": 5, "values": values}],
        }
    )
    listings = AsyncMock(return_value={"listings": [{"asking_price_aed": 85000}] * 3})
    delivery = AsyncMock(
        return_value=SimpleNamespace(model_dump=lambda **kwargs: {"rows": [{"units": 120}]})
    )
    projects = AsyncMock(
        return_value={
            "projects": [
                {
                    "project_name_en": "Alpha",
                    "area_name_en": "Business Bay",
                    "percent_completed": 60,
                },
                {
                    "project_name_en": "Beta",
                    "area_name_en": "Business Bay",
                    "percent_completed": 20,
                },
            ],
            "payment_plans": None,
        }
    )
    monkeypatch.setattr(reports, "get_market_evidence", metrics)
    monkeypatch.setattr(reports, "get_listing_evidence", listings)
    monkeypatch.setattr(reports, "get_listing_inventory", listings)
    monkeypatch.setattr(reports, "get_delivery_summary", delivery)
    monkeypatch.setattr(reports, "get_project_evidence", projects)
    return SimpleNamespace(metrics=metrics, listings=listings, delivery=delivery, projects=projects)


def lease():
    return MarketRelease(
        "immutable-fixture", frozenset({"sales", "rentals", "listings", "projects"})
    )


async def test_rental_appraisal_composes_new_renewed_rents_and_exact_building_listings(domains):
    request = reports.ReportRequest(
        kind="rental_appraisal",
        building="Known Tower",
        location="JLT",
        bedrooms="2",
        period={"type": "rolling_days", "days": 90},
    )
    with use_market_release(lease()):
        result = await reports.compose_market_report(request, context=CONTEXT)
    assert result["supported_annual_asking_rent_range_aed"] == [70000, 90000]
    metric = domains.metrics.call_args.args[0]
    assert (metric.dataset, metric.building, metric.bedrooms, metric.group_by) == (
        "rentals",
        "Known Tower",
        ["2"],
        "contract_version",
    )
    assert metric.period.days == 90
    assert domains.listings.call_args.args[0].building == "Known Tower"
    assert domains.listings.call_args.args[0].mode == "rent"
    unpinned = await reports.compose_market_report(request, context=CONTEXT)
    assert unpinned["status"] == "unavailable"
    assert unpinned["supported_annual_asking_rent_range_aed"] is None


async def test_monthly_report_preserves_previous_complete_month_and_no_invented_change(domains):
    request = reports.ReportRequest(kind="monthly_area", location="Business Bay")
    result = await reports.compose_market_report(request, context=CONTEXT)
    assert result["status"] == "unavailable"
    assert set(result["components"]) == {
        "sales",
        "rentals",
        "sale_listings",
        "rent_listings",
        "scheduled_delivery",
    }
    for call in domains.metrics.call_args_list:
        assert call.args[0].period.type == "previous_month"
        assert call.args[0].compare_with_previous_period is True
        assert call.kwargs["context"] is CONTEXT
    assert domains.delivery.call_args.kwargs["reference_date"] == date(2026, 10, 3)
    assert domains.delivery.call_args.kwargs["delivery_statuses"] == ("scheduled_in_horizon",)


async def test_off_plan_report_keeps_missing_catalogue_data_and_resolves_named_projects(domains):
    request = reports.ReportRequest(kind="off_plan_comparison", projects=["Alpha", "Beta"])
    with use_market_release(lease()):
        result = await reports.compose_market_report(request, context=CONTEXT)
    assert result["status"] == "ok"
    assert result["components"]["project_register"]["payment_plans"] is None
    assert result["components"]["project_register"]["projects"][0]["percent_completed"] == 60
    assert domains.metrics.await_count == 2
    assert all(call.args[0].location == "Business Bay" for call in domains.metrics.call_args_list)
    domains.projects.return_value["projects"].append(
        {"project_name_en": "Alpha", "area_name_en": "JVC"}
    )
    domains.metrics.reset_mock()
    result = await reports.compose_market_report(request, context=CONTEXT)
    assert result["status"] == "clarification_required"
    assert result["required_bindings"] == ["Alpha"]
    domains.metrics.assert_not_awaited()


async def test_unbound_report_does_not_select_another_entity(domains):
    result = await reports.compose_market_report(
        reports.ReportRequest(kind="seller_competition", location="Downtown Dubai", bedrooms="1"),
        context=CONTEXT,
    )
    assert result == {"status": "clarification_required", "required_bindings": ["building"]}
    domains.metrics.assert_not_awaited()
    domains.listings.assert_not_awaited()
