"""Listing valuation's own DLD-sales comparables (listing underpricing, 11 Nov 2026).

The CRM owner valuation model is deliberately not used or changed: listings value themselves
from ready sales of the same bedroom count in the same building.
"""

from datetime import date

from app.listings import comparables
from app.listings.comparables import ListingHome, SalesStats, estimate_value


def _home(**extra):
    values = {"property_type": "Apartment", "bedrooms": "2 Bed", "size_sqft": 1000.0}
    values.update(extra)
    return ListingHome(**values)


def _comps(**levels):
    names = ("building_type_beds", "building_type", "area_type_beds", "area_type")
    return {name: levels.get(name) for name in names}


async def test_stats_sql_uses_ready_sales_and_counts_a_bulk_deal_once(monkeypatch):
    captured = {}

    async def fake_query(sql, params):
        captured["sql"], captured["params"] = sql, params
        return []

    monkeypatch.setattr(comparables, "query", fake_query)
    await comparables.fetch_sales_stats(["b"], ["a"], date(2025, 11, 11), date(2026, 11, 12))
    sql = captured["sql"]
    # Off-plan launches sell at a premium; a ready listing is compared with ready sales only.
    assert sql.count("market_status = 'Ready'") == 4
    # Units sold together on one day at one price per sqft are one piece of evidence.
    assert sql.count("transaction_date, round(log(price_per_sqft_aed) * 100)") == 4
    assert "AS price" in sql and "AS size_p50" in sql
    assert captured["params"]["since"] == "2025-11-11"


def test_apartment_is_psf_times_size_with_a_five_percent_floor():
    stats = SalesStats(6, 1995, 2000, 2005, size_p50=1000.0)
    result = estimate_value(_home(), _comps(building_type_beds=stats))
    assert (result.estimated_value_aed, result.low_aed, result.high_aed) == (
        2_000_000,
        1_900_000,
        2_100_000,
    )
    assert (result.confidence, result.detail["basis"]) == ("high", "psf_size")
    assert result.detail["comparable_size_sqft"] == 1000


def test_villa_is_valued_from_bedroom_price_not_size():
    # DLD size 1,215 sqft is the plot; 4BR villas in the building sell for about 2.1M (Verona).
    stats = SalesStats(6, 900, 935, 980, 1_950_000, 2_100_000, 2_250_000)
    result = estimate_value(
        _home(property_type="Villa", bedrooms="4 Bed", size_sqft=1215.0),
        _comps(building_type_beds=stats),
    )
    assert result.estimated_value_aed == 2_100_000
    assert result.detail["basis"] == "bedroom_price"


def test_ladder_needs_five_building_or_ten_area_sales():
    thin = SalesStats(4, 1800, 2000, 2200)
    area = SalesStats(12, 900, 1000, 1100)
    result = estimate_value(_home(), _comps(building_type_beds=thin, area_type_beds=area))
    assert (result.detail["level"], result.confidence) == ("area_type_beds", "medium")
    assert estimate_value(_home(), _comps(area_type=SalesStats(9, 1, 1, 1))) is None


def test_stats_row_carries_price_and_size():
    stats = comparables.stats_from_row(
        {"count": 6, "psf": [900.0, 935.0, 980.0], "price": [1.0, 2.0, 3.0], "size_p50": 1215.0}
    )
    assert (stats.price_p50, stats.size_p50) == (2.0, 1215.0)
