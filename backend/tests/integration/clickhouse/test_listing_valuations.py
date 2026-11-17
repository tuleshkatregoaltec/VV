"""Execute valuation filtering and atomic publication against a disposable local warehouse."""

import json
import sys
from datetime import date
from unittest.mock import AsyncMock

import pytest

from app.listings import queries
from app.listings.valuation_service import COLUMNS, CREATE_TABLE, TABLE
from scripts.listings import value_listings


def _valuation(key, asking=1_800_000):
    row = dict.fromkeys(COLUMNS, 0)
    row.update(
        listing_id=key,
        estimate_aed=2_000_000,
        low_aed=1_900_000,
        high_aed=2_100_000,
        confidence="high",
        level="building_type_beds",
        basis="psf_size",
        building_key="tower",
        market_position="below_market",
        value_gap_pct=-0.1,
        asking_aed=asking,
        bedrooms="2 Bed",
        size_sqft=1000.0,
        version="test",
        valued_at=date(2026, 11, 5),
    )
    return row


async def _seed(warehouse, install_serving):
    await install_serving(tables=("pf_listings_bronze",), views=())
    await warehouse.command(CREATE_TABLE)
    fields = [
        "listing_id",
        "reference",
        "category_id",
        "is_available",
        "price_json",
        "size_json",
        "bedrooms",
        "raw_property_json",
        "listing_location_names_json",
    ]
    rows = []
    for key, price, status, category in [
        ("A", 1_800_000, "completed", 1),
        ("B", 1_800_000, "completed", 1),
        ("changed", 2_400_000, "completed", 1),
        ("offplan", 1_800_000, "off_plan", 1),
        ("rent", 1_800_000, "completed", 2),
    ]:
        rows.append(
            [
                key,
                "REF-" + key,
                category,
                1,
                json.dumps({"value": price}),
                '{"value":1000}',
                "2",
                json.dumps({"property_type": "apartment", "completion_status": status}),
                '["Dubai","Marina","Tower"]',
            ]
        )
    await warehouse.insert("pf_listings_bronze", rows, column_names=fields)
    await warehouse.insert(
        TABLE,
        [[_valuation(row[0])[c] for c in COLUMNS] for row in rows],
        column_names=list(COLUMNS),
    )


async def test_filtered_duplicate_and_changed_price_analytics(warehouse, install_serving):
    await _seed(warehouse, install_serving)
    filters = dict(
        mode="sale",
        search=None,
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=None,
        price_max=None,
    )
    counts = await queries.fetch_valuation_counts(filters)
    assert counts[0]["below_market_count"] == 2  # only the two current ready-sale rows
    market_filter = {**filters, "market_position": "below_market"}
    assert (await queries.fetch_listing_count(market_filter))[0]["total"] == 1
    # A wins an unfiltered dedupe, but the exact reference search must still find B.
    filtered = {**market_filter, "search": "REF-B"}
    assert (await queries.fetch_listing_count(filtered))[0]["total"] == 1
    rows = await queries.fetch_listing_rows(
        filtered, limit=10, offset=0, sort="value_gap", with_valuations=True
    )
    assert [row["listing_id"] for row in rows] == ["B"]
    assert (await queries.fetch_listing_count({**market_filter, "search": "REF-changed"}))[0][
        "total"
    ] == 0


async def test_cli_atomic_exchange_keeps_last_release_for_rollback(warehouse, monkeypatch):
    await warehouse.command(CREATE_TABLE)
    previous, current = _valuation("previous"), _valuation("current")
    await warehouse.insert(TABLE, [[previous[c] for c in COLUMNS]], column_names=list(COLUMNS))
    monkeypatch.setattr(sys, "argv", ["value_listings.py"])
    monkeypatch.setattr(value_listings, "_rows", AsyncMock(return_value=[{}]))
    monkeypatch.setattr(value_listings, "value_listing_rows", AsyncMock(return_value=[current]))
    monkeypatch.setattr(value_listings, "close_clickhouse", AsyncMock())
    await value_listings.main()
    assert (await warehouse.query(f"SELECT listing_id FROM {TABLE}")).result_rows == [("current",)]
    tables = (await warehouse.query("SHOW TABLES")).result_rows
    retained = [name for (name,) in tables if name.startswith(TABLE + "_staging_")]
    assert len(retained) == 1
    assert (await warehouse.query(f"SELECT listing_id FROM {retained[0]}")).result_rows == [
        ("previous",)
    ]


async def test_real_insert_failure_preserves_serving_release(warehouse, monkeypatch):
    await warehouse.command(CREATE_TABLE)
    previous = _valuation("previous")
    await warehouse.insert(TABLE, [[previous[c] for c in COLUMNS]], column_names=list(COLUMNS))
    bad = _valuation("current")
    bad["estimate_aed"] = "invalid UInt64"
    monkeypatch.setattr(sys, "argv", ["value_listings.py"])
    monkeypatch.setattr(value_listings, "_rows", AsyncMock(return_value=[{}]))
    monkeypatch.setattr(value_listings, "value_listing_rows", AsyncMock(return_value=[bad]))
    monkeypatch.setattr(value_listings, "close_clickhouse", AsyncMock())
    with pytest.raises((TypeError, ValueError)):
        await value_listings.main()
    assert (await warehouse.query(f"SELECT listing_id FROM {TABLE}")).result_rows == [("previous",)]
