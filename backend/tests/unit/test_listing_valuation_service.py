"""Batch valuation of sale listings from DLD sales (listing underpricing, 11 Nov 2026)."""

from datetime import date

import pytest

from app.listings import comparables, valuation_service
from app.listings import queries as listing_queries

TODAY = date(2026, 11, 11)


def _row(listing_id="L1", names=None, **extra):
    row = {
        "listing_id": listing_id,
        "category_id": 1,
        "location_names": names
        or ["Dubai", "Town Square", "Hayat Boulevard", "Hayat Boulevard 2A"],
        "property_type": "apartment",
        "completion_status": "completed",
        "bedrooms": "2",
        "price_aed": 1_800_000,
        "size_sqft": 1000.0,
    }
    row.update(extra)
    return row


def _stats(level, building="", area="", beds="", count=6, p50=2000.0):
    return {
        "level": level,
        "building_key": building,
        "area_key": area,
        "property_type": "Apartment",
        "bedrooms": beds,
        "count": count,
        "psf": [p50 * 0.95, p50, p50 * 1.05],
        "price": [0.0, 0.0, 0.0],
        "size_p50": 1000.0,
    }


def _sale(unit, size, price):
    return {
        "building_key": "hayatboulevard",
        "property_type": "Apartment",
        "bedrooms": "2 Bed",
        "unit_key": unit,
        "unit_number": unit,
        "transaction_date": date(2026, 9, 1),
        "sale_amount_aed": price,
        "size_sqft": size,
    }


@pytest.fixture
def stats(monkeypatch):
    state = {"rows": [], "calls": [], "sales": [_sale(str(i), 1000.0, 2_000_000) for i in range(5)]}

    async def sales(building_keys, since):
        return state["sales"]

    monkeypatch.setattr(listing_queries, "fetch_ready_sales_for_buildings", sales)

    async def fake(building_keys, area_keys, since, until):
        state["calls"].append((sorted(building_keys), sorted(area_keys)))
        return state["rows"]

    monkeypatch.setattr(comparables, "fetch_sales_stats", fake)
    return state


async def test_value_listing_rows_picks_first_candidate_with_stats(stats):
    # The building leaf "hayatboulevard2a" has no DLD sales; the project key does.
    stats["rows"] = [_stats("building_type_beds", building="hayatboulevard", beds="2 Bed")]
    [result] = await valuation_service.value_listing_rows([_row()], TODAY)
    assert result["building_key"] == "hayatboulevard"
    assert result["confidence"] == "high"
    assert result["estimate_aed"] == 2_000_000
    assert result["market_position"] == "below_market"
    assert result["value_gap_pct"] == -0.1
    assert result["version"] == "listing-value-v1"
    assert stats["calls"] == [(["hayatboulevard", "hayatboulevard2a"], ["townsquare"])]


async def test_value_listing_rows_skips_unvaluable(stats):
    assert (
        await valuation_service.value_listing_rows([_row(completion_status="off_plan")], TODAY)
        == []
    )
    assert stats["calls"] == []


async def test_unmatched_building_uses_area_and_is_not_flagged(stats):
    stats["rows"] = [_stats("area_type", area="townsquare", count=40, p50=2000.0)]
    [result] = await valuation_service.value_listing_rows([_row(price_aed=1_000_000)], TODAY)
    assert result["building_key"] == ""
    assert result["confidence"] == "low"
    assert result["market_position"] == "insufficient_data"


def test_bargains_dedupe_same_unit():
    a = {"building_key": "b", "bedrooms": "2 Bed", "size_sqft": 1000.0, "asking_aed": 1_800_000}
    b = {**a, "size_sqft": 1004.0}
    c = {**a, "asking_aed": 1_750_000}
    assert valuation_service.dedupe_key(a) == valuation_service.dedupe_key(b)
    assert valuation_service.dedupe_key(a) != valuation_service.dedupe_key(c)


def test_schema_file_matches_backend_table_definition():
    # holocron's schema file documents the table; both definitions must stay identical.
    import re
    from pathlib import Path

    schema = Path(__file__).parents[3] / "holocron/holocron/lib/sql/clickhouse_schema.sql"
    text = schema.read_text()
    start = text.index("CREATE TABLE IF NOT EXISTS listing_valuations")
    documented = text[start : text.index(";", start)]
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    assert norm(documented) == norm(valuation_service.CREATE_TABLE)


async def test_flag_comes_from_the_closest_sales_not_the_building_psf(stats):
    # Grande 2BR: building-wide 2BR psf says 2.0M, but the closest-size sales sold at ~1.8M.
    stats["rows"] = [_stats("building_type_beds", building="hayatboulevard", beds="2 Bed")]
    stats["sales"] = [_sale(str(i), 1000.0, 1_800_000 + i * 10_000) for i in range(5)]
    [result] = await valuation_service.value_listing_rows([_row(price_aed=1_800_000)], TODAY)
    assert result["estimate_aed"] == 1_820_000
    assert result["market_position"] == "near_market"
    assert result["exact_count"] == 5


async def test_fewer_than_three_exact_sales_is_not_flagged(stats):
    stats["rows"] = [_stats("building_type_beds", building="hayatboulevard", beds="2 Bed")]
    stats["sales"] = [_sale("1", 1000.0, 2_000_000), _sale("2", 1600.0, 3_000_000)]
    [result] = await valuation_service.value_listing_rows([_row()], TODAY)
    assert result["market_position"] == "insufficient_data"
    assert result["exact_count"] == 1


async def test_thin_building_leaf_does_not_shadow_the_project(stats):
    # "Hayat Boulevard 2A" has 2 sales, "Hayat Boulevard" has 40: value from the project.
    stats["rows"] = [
        _stats("building_type_beds", building="hayatboulevard2a", beds="2 Bed", count=2),
        _stats("building_type", building="hayatboulevard2a", count=2),
        _stats("building_type_beds", building="hayatboulevard", beds="2 Bed", count=40),
    ]
    [result] = await valuation_service.value_listing_rows([_row()], TODAY)
    assert result["building_key"] == "hayatboulevard"
    assert result["level"] == "building_type_beds"


async def test_every_considered_listing_gets_a_row(stats):
    # Rows for unvalued listings too, so a rewrite retires an old flag (stored as not flagged).
    [result] = await valuation_service.value_listing_rows([_row()], TODAY)
    assert result["market_position"] == "insufficient_data"
    assert result["estimate_aed"] == 0
