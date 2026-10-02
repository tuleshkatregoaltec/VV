"""Independent arithmetic and support rules: sparse or unpinned facts cannot become yields."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.clickhouse import client
from app.listings.capabilities import registered_rent_yield
from app.market.evidence import (
    MarketRelease,
    SourceCoverage,
    has_shared_release,
    use_market_release,
)
from app.market.reports import ReportRequest, report_conclusions


def rents(count=5, status="complete"):
    # Five registered annual rents: 60k, 70k, 80k, 90k, 100k -> median 80k; IQR 70k–90k.
    values = {"median_aed": 80000, "p25_aed": 70000, "p75_aed": 90000}
    return {
        "coverage": {"status": status},
        "total": {"count": count, "values": values},
        "rows": [{"group": "New", "count": count, "values": values}],
    }


def test_gross_yield_uses_annual_registered_rents_and_asking_price_with_support():
    result = registered_rent_yield({"asking_price_aed": 1_000_000}, rents(), pinned=True)
    assert result == {
        "gross_yield_pct": 8.0,
        "gross_yield_range_pct": [7.0, 9.0],
        "yield_status": "ok",
    }
    for source, pinned in [
        (rents(4), True),
        (rents(status="unverified"), True),
        (rents(), False),
        (None, True),
    ]:
        assert (
            registered_rent_yield({"asking_price_aed": 1_000_000}, source, pinned=pinned)[
                "yield_status"
            ]
            == "unavailable"
        )


def test_appraisal_requires_new_contract_support_and_competing_listings():
    request = ReportRequest(kind="rental_appraisal", building="Tower", location="JLT", bedrooms="2")
    data = {"rentals": rents(), "rent_listings": {"listings": [{"asking_price_aed": 85000}] * 3}}
    assert report_conclusions(request, data, pinned=True)[
        "supported_annual_asking_rent_range_aed"
    ] == [70000, 90000]
    assert (
        report_conclusions(request, data, pinned=False)["supported_annual_asking_rent_range_aed"]
        is None
    )
    data["rentals"]["rows"][0]["group"] = "Renewed"
    assert (
        report_conclusions(request, data, pinned=True)["supported_annual_asking_rent_range_aed"]
        is None
    )


def test_seller_asking_position_is_relative_to_achieved_sales_not_listings():
    request = ReportRequest(
        kind="seller_competition",
        building="Tower",
        location="Downtown Dubai",
        bedrooms="1",
        asking_price_aed=1_800_000,
    )
    data = {
        "sales": {
            "coverage": {"status": "complete"},
            "total": {
                "count": 5,
                "values": {"median_aed": 1_500_000, "p25_aed": 1_200_000, "p75_aed": 1_700_000},
            },
        }
    }
    position = report_conclusions(request, data, pinned=True)["owner_asking_position"]
    assert position["difference_from_achieved_median_pct"] == 20.0
    assert position["relative_to_achieved_iqr"] == "above"


def test_release_coverage_is_source_and_period_specific_and_scope_is_reset():
    release = MarketRelease(
        "fixture-immutable-1",
        frozenset({"rentals", "listings"}),
        (SourceCoverage("rentals", date(2026, 9, 1), date(2026, 9, 30), "complete"),),
    )
    with use_market_release(release):
        assert has_shared_release("rentals", "listings")
        assert not has_shared_release("sales", "listings")
        assert release.covers("rentals", date(2026, 9, 1), date(2026, 9, 30))
        assert not release.covers("rentals", date(2026, 8, 1), date(2026, 9, 30))
    assert not has_shared_release("rentals")


async def test_query_limits_are_task_scoped_and_fail_instead_of_truncating(monkeypatch):
    warehouse = SimpleNamespace(
        query=AsyncMock(return_value=SimpleNamespace(column_names=["n"], result_rows=[[1]]))
    )
    monkeypatch.setattr(client, "get_client", AsyncMock(return_value=warehouse))
    with (
        pytest.raises(RuntimeError),
        client.bounded_queries(
            max_execution_time=15, max_result_rows=1000, max_result_bytes=262144
        ),
    ):
        assert await client.query("SELECT 1") == [{"n": 1}]
        settings = warehouse.query.call_args.kwargs["settings"]
        assert settings["result_overflow_mode"] == "throw"
        assert settings["max_execution_time"] == 15
        raise RuntimeError("cancelled path")
    await client.query("SELECT 1")
    assert "settings" not in warehouse.query.call_args.kwargs


async def test_legacy_event_extrema_never_claim_verified_coverage(monkeypatch):
    from app.analytics import evidence
    from app.analytics.models import MarketMetricsRequest
    from app.market.evidence import MarketAccessContext

    domain = {
        "total": {"count": 5, "values": {"median_aed": 80000}},
        "coverage": {"status": "complete", "note": "Data covers all September."},
        "comparison_coverage": {"status": "complete", "note": "Data covers all August."},
        "change_pct": {"median_aed": 20.0},
        "limitations": [],
    }
    period = SimpleNamespace(start=date(2026, 9, 1), end=date(2026, 9, 30))
    result = SimpleNamespace(
        model_dump=lambda **kwargs: {**domain}, period=period, comparison_period=period
    )
    monkeypatch.setattr(
        evidence.market_metrics, "get_market_metrics", AsyncMock(return_value=result)
    )
    actor = MarketAccessContext("u", "o", date(2026, 10, 3), "t")
    request = MarketMetricsRequest(
        dataset="rentals",
        period={"type": "previous_month"},
        reference_date=date(2000, 1, 1),
        compare_with_previous_period=True,
    )
    payload = await evidence.get_market_evidence(request, context=actor)
    assert payload["total"] == domain["total"]
    assert payload["coverage"]["status"] == "unverified"
    assert payload["change_pct"] == {}
    assert evidence.market_metrics.get_market_metrics.call_args.args[0].reference_date == date(
        2026, 10, 3
    )
