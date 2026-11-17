"""Listings API reads stored DLD-sales valuations (listing underpricing, 11 Nov 2026)."""

from datetime import date

import pytest

from app.listings import queries, service

SALE_ROW = {
    "listing_id": "L1",
    "category_id": 1,
    "title": "2BR Hayat Boulevard",
    "price_json": '{"value": 1800000}',
    "size_json": '{"value": 1000, "unit": "sqft"}',
    "bedrooms": "2",
    "listing_location_names_json": '["Dubai", "Town Square", "Hayat Boulevard", "Hayat Boulevard 2A"]',
    "raw_property_json": '{"property_type": "apartment", "completion_status": "completed"}',
    "market_price_aed": 1_800_000,
    "size_sqft": 1000.0,
    "v_estimate_aed": 2_000_000,
    "v_asking_aed": 1_800_000,
    "v_low_aed": 1_900_000,
    "v_high_aed": 2_100_000,
    "v_confidence": "high",
    "v_level": "building_type_beds",
    "v_basis": "psf_size",
    "v_comparable_count": 6,
    "v_market_position": "below_market",
    "v_value_gap_pct": -0.1,
    "v_building_key": "hayatboulevard",
}


@pytest.fixture
def api(monkeypatch):
    state = {"rows": [dict(SALE_ROW)], "available": True, "row_calls": []}

    async def available():
        return state["available"]

    async def rows(filters, *, limit, offset, sort="default", with_valuations=False):
        state["row_calls"].append((filters, sort, with_valuations))
        return state["rows"]

    async def empty(*args, **kwargs):
        return []

    async def count(filters):
        return [{"total": len(state["rows"])}]

    async def freshness(params):
        return [{"refreshed": "2026-05-27 13:19:20"}]

    monkeypatch.setattr(queries, "valuations_available", available)
    monkeypatch.setattr(queries, "fetch_listing_rows", rows)
    monkeypatch.setattr(queries, "fetch_listing_benchmarks", empty)
    monkeypatch.setattr(queries, "fetch_listing_count", count)
    monkeypatch.setattr(queries, "fetch_inventory_freshness", freshness)
    return state


async def test_sale_card_uses_stored_dld_valuation(api):
    result = await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    card = result.listings[0]
    assert card.valuation_method == "dld_sales"
    assert (
        card.estimated_value_aed,
        card.estimated_value_low_aed,
        card.estimated_value_high_aed,
    ) == (
        2_000_000,
        1_900_000,
        2_100_000,
    )
    assert card.valuation_confidence == "high"
    assert card.market_position == "below_market"
    assert card.value_gap_pct == -0.1
    assert card.market_estimate_aed == 2_000_000
    assert card.comparable_count == 6
    assert card.is_off_plan is False
    assert api["row_calls"][0][2] is True


async def test_ready_sale_without_valuation_is_not_flagged_by_asking_peers(api):
    api["rows"] = [{k: v for k, v in SALE_ROW.items() if not k.startswith("v_")}]
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.valuation_method == "dld_sales"
    assert card.market_position == "insufficient_data"
    assert card.estimated_value_aed is None


async def test_rent_card_keeps_asking_peers_method(api):
    api["rows"] = [{**SALE_ROW, "category_id": 2}]
    card = (
        await service.list_listings_from_clickhouse(mode="rent", include_filters=False)
    ).listings[0]
    assert card.valuation_method == "asking_peers"
    assert card.estimated_value_aed is None
    assert api["row_calls"][0][2] is False


async def test_offplan_sale_is_marked_and_keeps_asking_peers(api, monkeypatch):
    # Asking peers would call this off-plan listing 28% below market (1,800 vs 2,500 AED/sqft).
    async def peers(params, mode):
        return [
            {
                "category_id": 1,
                "benchmark_peer_location": "",
                "benchmark_property_type": "",
                "bedrooms": "2",
                "benchmark_size_bucket": 0,
                "market_median_price_per_sqft_aed": 2500.0,
                "comparable_count": 10,
            }
        ]

    monkeypatch.setattr(queries, "fetch_listing_benchmarks", peers)
    api["rows"] = [
        {
            **{k: v for k, v in SALE_ROW.items() if not k.startswith("v_")},
            "raw_property_json": '{"property_type": "apartment", "completion_status": "off_plan"}',
            "has_valid_benchmark_size": True,
        }
    ]
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.is_off_plan is True
    assert card.valuation_method == "asking_peers"


async def test_missing_table_falls_back_to_asking_peers(api):
    api["available"] = False
    result = await service.list_listings_from_clickhouse(
        mode="sale", include_filters=False, market_position="below_market", sort="value_gap"
    )
    assert api["row_calls"] == []
    assert (result.total, result.listings) == (0, [])


async def test_missing_table_plain_list_falls_back_to_asking_peers(api):
    api["available"] = False
    result = await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    filters, sort, with_valuations = api["row_calls"][0]
    assert with_valuations is False and sort == "default"
    assert result.listings[0].valuation_method == "asking_peers"


async def test_list_response_carries_data_as_of(api):
    result = await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    assert result.data_as_of.date() == date(2026, 5, 27)


async def test_market_position_filter_and_value_gap_sort_sql(monkeypatch):
    captured = {}

    async def fake_query(sql, params):
        captured["sql"], captured["params"] = sql, params
        return []

    monkeypatch.setattr(queries, "query", fake_query)
    filters = dict(
        mode="sale",
        search=None,
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=None,
        price_max=None,
        market_position="below_market",
    )
    await queries.fetch_listing_rows(
        filters, limit=10, offset=0, sort="value_gap", with_valuations=True
    )
    sql = captured["sql"]
    assert "LEFT JOIN" in sql and "listing_valuations FINAL" in sql
    assert "LIMIT 1 BY v_building_key, bedrooms" in sql  # the same unit listed twice shows once
    assert sql.index("v_value_gap_pct") < sql.index("LIMIT {limit")
    assert captured["params"]["market_position"] == "below_market"


async def test_detail_carries_closest_sales(monkeypatch):
    async def available():
        return True

    async def detail(params):
        return [{k: v for k, v in SALE_ROW.items() if not k.startswith("v_")}]

    async def valuation(params):
        return [{k: v for k, v in SALE_ROW.items() if k.startswith("v_")}]

    async def sales(params):
        assert params["building"] == "hayatboulevard" and params["beds"] == "2 Bed"
        return [
            {
                "unit_key": "101",
                "unit_number": "101",
                "transaction_date": date(2026, 9, 1),
                "sale_amount_aed": 2_000_000,
                "size_sqft": 1000.0,
            },
            {
                "unit_key": "102",
                "unit_number": "102",
                "transaction_date": date(2026, 8, 1),
                "sale_amount_aed": 2_050_000,
                "size_sqft": 1010.0,
            },
        ]

    monkeypatch.setattr(queries, "valuations_available", available)
    monkeypatch.setattr(queries, "fetch_listing_detail", detail)
    monkeypatch.setattr(queries, "fetch_listing_valuation", valuation)
    monkeypatch.setattr(queries, "fetch_building_sales", sales)
    listing = await service.get_listing_from_clickhouse("L1")
    assert listing.valuation_method == "dld_sales"
    assert [c.unit for c in listing.valuation_comparables] == ["101", "102"]
    assert listing.valuation_comparables[0].price_aed == 2_000_000


async def test_villa_evidence_is_the_latest_same_bedroom_sales(monkeypatch):
    villa = {
        **{k: v for k, v in SALE_ROW.items() if not k.startswith("v_")},
        "listing_location_names_json": '["Dubai", "Damac Hills 2", "Verona"]',
        "raw_property_json": '{"property_type": "villa", "completion_status": "completed"}',
        "bedrooms": "4",
        "size_json": '{"value": 2400, "unit": "sqft"}',
    }
    stored = {
        **{k: v for k, v in SALE_ROW.items() if k.startswith("v_")},
        "v_basis": "bedroom_price",
        "v_building_key": "verona",
        "v_level": "building_type_beds",
    }

    async def available():
        return True

    async def detail(params):
        return [villa]

    async def valuation(params):
        return [stored]

    async def sales(params):
        # DLD records the plot (~1,215 sqft), far from the listing's 2,400 sqft built-up area.
        return [
            {
                "unit_key": str(i),
                "unit_number": str(i),
                "transaction_date": date(2026, 9 - i, 1),
                "sale_amount_aed": 2_000_000 + i,
                "size_sqft": 1215.0,
            }
            for i in range(7)
        ]

    monkeypatch.setattr(queries, "valuations_available", available)
    monkeypatch.setattr(queries, "fetch_listing_detail", detail)
    monkeypatch.setattr(queries, "fetch_listing_valuation", valuation)
    monkeypatch.setattr(queries, "fetch_building_sales", sales)
    listing = await service.get_listing_from_clickhouse("V1")
    assert [c.unit for c in listing.valuation_comparables] == ["0", "1", "2", "3", "4"]


async def test_unflagged_estimate_exposes_no_gap(api):
    # A suppressed estimate (area level, data error...) must not show a discount anywhere.
    api["rows"] = [{**SALE_ROW, "v_market_position": "insufficient_data", "v_value_gap_pct": -0.67}]
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.market_position == "insufficient_data"
    assert (card.value_gap_pct, card.market_delta_pct, card.market_estimate_aed) == (
        None,
        None,
        None,
    )


async def test_price_changed_since_valuation_is_not_flagged(api):
    api["rows"] = [{**SALE_ROW, "v_asking_aed": 2_000_000}]  # valued at 2.0M, now listed at 1.8M
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.market_position == "insufficient_data"


async def test_card_carries_valuation_date(api):
    api["rows"] = [{**SALE_ROW, "v_valued_at": date(2026, 11, 11)}]
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.valued_at == date(2026, 11, 11)


async def test_value_gap_sort_ranks_only_flagged_listings(monkeypatch):
    captured = {}

    async def fake_query(sql, params):
        captured["sql"] = sql
        return []

    monkeypatch.setattr(queries, "query", fake_query)
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
    await queries.fetch_listing_rows(
        filters, limit=10, offset=0, sort="value_gap", with_valuations=True
    )
    assert "v_market_position IN ('below_market', 'near_market', 'above_market')" in captured["sql"]


async def test_bargains_dedupe_only_considers_available_listings(monkeypatch):
    where, _ = queries._where_sql(
        mode="sale",
        search=None,
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=None,
        price_max=None,
        market_position="below_market",
    )
    sub = where[where.index("listing_valuations") :]
    assert sub.index("is_available = 1") < sub.index("LIMIT 1 BY")


async def test_commercial_sale_analytics_keep_asking_peer_counts(monkeypatch):
    calls = []

    async def available():
        return True

    async def fake_query(sql, params):
        calls.append(sql)
        return [{"total": 5, "below_market_count": 2, "benchmarked_count": 4}]

    monkeypatch.setattr(queries, "valuations_available", available)
    monkeypatch.setattr(service.queries, "query", fake_query)
    analytics = await service.listing_analytics_from_clickhouse(
        mode="sale", asset_class="commercial"
    )
    assert analytics.below_market_count == 2
    assert not any("v_market_position" in sql for sql in calls)


async def test_detail_evidence_uses_the_valuation_window(monkeypatch):
    async def available():
        return True

    async def detail(params):
        return [{k: v for k, v in SALE_ROW.items() if not k.startswith("v_")}]

    async def valuation(params):
        return [
            {
                **{k: v for k, v in SALE_ROW.items() if k.startswith("v_")},
                "v_valued_at": date(2026, 6, 1),
            }
        ]

    seen = {}

    async def sales(params):
        seen.update(params)
        return []

    monkeypatch.setattr(queries, "valuations_available", available)
    monkeypatch.setattr(queries, "fetch_listing_detail", detail)
    monkeypatch.setattr(queries, "fetch_listing_valuation", valuation)
    monkeypatch.setattr(queries, "fetch_building_sales", sales)
    await service.get_listing_from_clickhouse("L1")
    assert (seen["since"], seen["until"]) == (date(2025, 6, 1), date(2026, 6, 2))


@pytest.mark.parametrize(
    "changed",
    [
        {"v_asking_aed": None},
        {"category_id": 3},
        {
            "raw_property_json": '{"property_type":"apartment","completion_status":"under_construction"}'
        },
    ],
)
async def test_stored_valuation_requires_a_current_ready_sale_subject(api, changed):
    api["rows"] = [{**SALE_ROW, **changed}]
    card = (
        await service.list_listings_from_clickhouse(mode="sale", include_filters=False)
    ).listings[0]
    assert card.market_position != "below_market"


async def test_market_filter_deduplicates_only_after_all_requested_filters(monkeypatch):
    filters = dict(
        mode="sale",
        search="REF-B",
        area="Marina",
        property_type="apartment",
        bedrooms="2",
        bedrooms_in=None,
        price_min=1_000_000,
        price_max=3_000_000,
        market_position="below_market",
    )
    where, parameters = queries._where_sql(**filters)
    inner = where[where.index("SELECT listing_id FROM") :]
    for predicate in (
        "reference, {search:String}",
        "= {area:String}",
        "= {property_type:String}",
        "bedrooms = {bedrooms:String}",
        ">= {price_min:Int64}",
        "<= {price_max:Int64}",
    ):
        assert predicate in inner[: inner.index("LIMIT 1 BY")]
    assert parameters["search"] == "REF-B"
    assert queries._CURRENT_VALUATION in inner

    captured = []

    async def query(sql, params):
        captured.append(sql)
        return []

    monkeypatch.setattr(queries, "query", query)
    await queries.fetch_valuation_counts(filters)
    await queries.fetch_listing_rows(
        filters, limit=10, offset=0, sort="value_gap", with_valuations=True
    )
    assert all(queries._CURRENT_VALUATION in sql for sql in captured)
    assert queries._CURRENT_VALUATION in captured[0][captured[0].rindex("WHERE") :]
    assert queries._CURRENT_VALUATION in captured[1][captured[1].rindex("ORDER BY") :]


def test_current_valuation_sql_rejects_changed_price_and_out_of_scope_listings():
    import json
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.create_function(
        "JSON_VALUE", 2, lambda raw, key: json.loads(raw).get(key.removeprefix("$."), "")
    )
    db.create_function("JSONExtractInt", 2, lambda raw, key: int(json.loads(raw).get(key, 0)))
    db.create_function("JSONExtractFloat", 2, lambda raw, key: float(json.loads(raw).get(key, 0)))
    db.create_function("trimBoth", 1, str.strip)
    try:
        for changes, expected in [
            ({}, 1),
            ({"price": 2_400_000}, 0),
            ({"category": 2}, 0),
            ({"status": "off_plan"}, 0),
            ({"status": "under_construction"}, 0),
            ({"asking": 0}, 0),
            ({"estimate": 0}, 0),
        ]:
            values = dict(
                category=1,
                price=1_800_000,
                asking=1_800_000,
                estimate=2_000_000,
                status="completed",
            )
            values.update(changes)
            sql = (
                """SELECT """
                + queries._CURRENT_VALUATION
                + """ FROM (
                SELECT :category AS category_id, :raw AS raw_property_json,
                       :price_json AS price_json, '{"value": 1000}' AS size_json,
                       :asking AS v_asking_aed, :estimate AS v_estimate_aed
            )"""
            )
            params = {
                **values,
                "raw": json.dumps(
                    {"property_type": "apartment", "completion_status": values["status"]}
                ),
                "price_json": json.dumps({"value": values["price"]}),
            }
            assert db.execute(sql, params).fetchone() == (expected,)
    finally:
        db.close()
