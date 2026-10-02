"""Real serving queries retain exact boundary ownership and source asking-price cents.

Reuse existing disposable fixtures; canonical amounts are Int64, so canonical rows use
adjacent whole AED while fractional thresholds and JSON listing prices exercise cents.
"""

import json
from datetime import datetime

import pytest
import test_chat_listing_capabilities as listing_fixtures
import test_market_metrics as metric_fixtures
from test_chat_listing_capabilities import CONTEXT, fixture_release
from test_market_metrics import RENT_COLUMNS, SALE_COLUMNS, rent, request, sale

from app.analytics.market_metrics import get_market_metrics
from app.listings import service
from app.listings.capabilities import (
    compare_listing_age,
    compare_listing_rents,
    get_listing_evidence,
    get_listing_inventory,
)
from app.listings.capability_models import (
    ListingAgeRequest,
    ListingEvidenceRequest,
    ListingRentRequest,
)
from app.market import evidence

inventory = listing_fixtures.inventory
served = metric_fixtures.served


@pytest.fixture
async def boundary_market(served):
    sales = [
        sale(
            f"boundary-s{index}",
            datetime(2026, 9, 15),
            "Sales",
            amount,
            100,
            "JUMEIRAH VILLAGE CIRCLE",
            building="Boundary Tower",
        )
        for index, amount in enumerate(
            [999_999, 1_000_000, 1_000_001, 1_999_999, 2_000_000, 2_000_001]
        )
    ]
    rentals = [
        rent(
            f"boundary-r{index}",
            datetime(2026, 9, 15),
            datetime(2026, 9, 1),
            datetime(2027, 8, 31),
            amount,
            amount,
            "New",
            "3 Beds",
        )
        for index, amount in enumerate([99_999, 100_000, 100_001])
    ]
    await served.insert("market_sale_events", sales, column_names=SALE_COLUMNS)
    await served.insert("market_rental_events", rentals, column_names=RENT_COLUMNS)
    return served


def market_request(dataset, **fields):
    return request(
        dataset=dataset,
        metrics=["count"],
        **({"building": "Boundary Tower"} if dataset == "sales" else {"bedrooms": ["3"]}),
        **fields,
    )


@pytest.mark.parametrize(
    "dataset, cutoff, above",
    [("sales", 1_000_000, 4), ("rentals", 100_000, 1)],
)
async def test_price_boundary_analytics_strict_inclusive_and_old_defaults(
    boundary_market, dataset, cutoff, above
):
    for filters, expected in [
        ({"max_value_aed": cutoff}, 1),  # Existing exclusive maximum.
        ({"max_value_aed": cutoff, "max_value_inclusive": True}, 2),
        ({"min_value_aed": cutoff}, above + 1),  # Existing inclusive minimum.
        ({"min_value_aed": cutoff, "min_value_inclusive": False}, above),
        ({"max_value_aed": cutoff - 0.01}, 1),
        ({"max_value_aed": cutoff + 0.01}, 2),
        ({"min_value_aed": cutoff - 0.01}, above + 1),
        ({"min_value_aed": cutoff + 0.01}, above),
        ({"min_value_aed": cutoff, "max_value_aed": cutoff, "max_value_inclusive": True}, 1),
    ]:
        result = await get_market_metrics(market_request(dataset, **filters))
        assert result.total.count == expected, filters


async def test_price_boundary_brackets_count_each_equality_once(boundary_market):
    for flags, labels, counts in [
        (
            None,
            ["under 1,000,000", "1,000,000 to under 2,000,000", "2,000,000 and above"],
            [1, 3, 2],
        ),
        (
            [False, True],
            ["under 1,000,000", "1,000,000 to including 2,000,000", "over 2,000,000"],
            [1, 4, 1],
        ),
        (
            [True, False],
            [
                "up to and including 1,000,000",
                "over 1,000,000 to under 2,000,000",
                "2,000,000 and above",
            ],
            [2, 2, 2],
        ),
        (
            [True, True],
            [
                "up to and including 1,000,000",
                "over 1,000,000 to including 2,000,000",
                "over 2,000,000",
            ],
            [2, 3, 1],
        ),
    ]:
        result = await get_market_metrics(
            market_request(
                "sales",
                group_by="price_band",
                price_bands=[1_000_000, 2_000_000],
                price_band_upper_inclusive=flags,
            )
        )
        assert [row.group for row in result.rows] == labels
        assert [row.count for row in result.rows] == counts
        assert sum(row.count for row in result.rows) == result.total.count == 6

    fractional = await get_market_metrics(
        market_request(
            "sales",
            group_by="price_band",
            price_bands=[999_999.99, 2_000_000.01],
            price_band_upper_inclusive=[False, True],
        )
    )
    assert [(row.group, row.count) for row in fractional.rows] == [
        ("under 999,999.99", 1),
        ("999,999.99 to including 2,000,000.01", 4),
        ("over 2,000,000.01", 1),
    ]


@pytest.fixture
async def boundary_inventory(inventory, install_serving):
    await install_serving(tables=("dxbi_sales_unit_events", "dxbi_rental_events"), views=())
    # Clone the existing one-bed JVC fixture, preserving its exact rent-comparable scope.
    for key, amount in [("below", 1_199_999.99), ("equal", 1_200_000), ("above", 1_200_000.01)]:
        await inventory.command(
            """INSERT INTO pf_listings_bronze
                (listing_id, category_id, price_json, size_json, bedrooms,
                 listing_location_names_json, raw_property_json, is_available, scraped_at, run_id)
                SELECT {key:String}, category_id, {price:String}, size_json, bedrooms,
                    listing_location_names_json, raw_property_json, is_available, scraped_at, run_id
                FROM pf_listings_bronze WHERE listing_id = 'yield-1'""",
            parameters={"key": key, "price": json.dumps({"value": amount, "currency": "AED"})},
        )
    return inventory


async def test_price_boundary_listings_shared_grid_aggregate_and_evidence_agree(boundary_inventory):
    for filters, expected in [
        ({"price_max": 1_200_000}, ["yield-1", "below", "equal"]),
        ({"price_max": 1_200_000, "price_max_inclusive": False}, ["yield-1", "below"]),
        ({"price_min": 1_200_000}, ["equal", "above"]),
        ({"price_min": 1_200_000, "price_min_inclusive": False}, ["above"]),
        ({"price_min": 1_199_999.99, "price_max": 1_200_000.01}, ["below", "equal", "above"]),
        (
            {
                "price_min": 1_199_999.99,
                "price_max": 1_200_000.01,
                "price_min_inclusive": False,
                "price_max_inclusive": False,
            },
            ["equal"],
        ),
    ]:
        spec = ListingEvidenceRequest(location="JVC", bedrooms="1", **filters)
        result = await get_listing_evidence(spec, context=CONTEXT)
        assert [row["listing_id"] for row in result["listings"]] == expected, filters
        aggregate = await get_listing_inventory(spec, context=CONTEXT)
        assert aggregate["inventory"]["total"] == len(expected)
        grid = await service.list_listings_from_clickhouse(
            "sale",
            area="Jumeirah Village Circle",
            bedrooms="1",
            **filters,
        )
        assert grid.total == len(expected)
        assert {row.listing_id for row in grid.listings} == set(expected)
    grid = await service.list_listings_from_clickhouse(
        "sale",
        area="Jumeirah Village Circle",
        price_min=1_200_000,
        price_min_inclusive=False,
    )
    assert grid.listings[0].price_value == 1_200_000.01
    assert grid.filters.price_max == 20_000_000  # All-inventory metadata retains existing scope.
    result = await get_listing_evidence(
        ListingEvidenceRequest(location="JVC", price_min=1_200_000, price_min_inclusive=False),
        context=CONTEXT,
    )
    assert result["listings"][0]["asking_price_aed"] == 1_200_000.01


async def test_price_boundary_gross_yield_excludes_exact_upper_limit_with_complete_pin(
    boundary_inventory,
):
    with evidence.use_market_release(fixture_release()):
        result = await compare_listing_rents(
            ListingRentRequest(
                location="JVC",
                bedrooms="1",
                price_min=1_199_999.98,
                price_max=1_200_000,
                price_max_inclusive=False,
                period={"type": "previous_month"},
            ),
            context=CONTEXT,
        )
    assert result["status"] == "ok"
    assert [row["listing_id"] for row in result["listings"]] == ["below"]
    assert result["listings"][0]["asking_price_aed"] == 1_199_999.99
    assert result["listings"][0]["gross_yield_pct"] == 6.67
    assert result["registered_rents"]["Fixture Tower"]["total"]["count"] == 5


async def test_price_boundary_rental_filters_compare_annual_amounts_with_cents(boundary_inventory):
    for key, amount, period in [
        ("rent-below", 120_000.11, "yearly"),
        ("rent-equal", 120_000.12, "yearly"),
        ("rent-monthly-equal", 10_000.01, "monthly"),
        ("rent-above", 120_000.13, "yearly"),
    ]:
        await boundary_inventory.command(
            """INSERT INTO pf_listings_bronze
                (listing_id, category_id, price_json, size_json, bedrooms,
                 listing_location_names_json, raw_property_json, is_available, scraped_at, run_id)
                SELECT {key:String}, 2, {price:String}, size_json, bedrooms,
                    listing_location_names_json, raw_property_json, is_available, scraped_at, run_id
                FROM pf_listings_bronze WHERE listing_id = 'yield-1'""",
            parameters={
                "key": key,
                "price": json.dumps({"value": amount, "period": period, "currency": "AED"}),
            },
        )
    for inclusive, expected in [
        (False, {"rent-below"}),
        (True, {"rent-below", "rent-equal", "rent-monthly-equal"}),
    ]:
        filters = {"price_max": 120_000.12, "price_max_inclusive": inclusive}
        result = await get_listing_evidence(
            ListingEvidenceRequest(mode="rent", location="JVC", bedrooms="1", **filters),
            context=CONTEXT,
        )
        assert {row["listing_id"] for row in result["listings"]} == expected
        aggregate = await get_listing_inventory(
            ListingEvidenceRequest(mode="rent", location="JVC", bedrooms="1", **filters),
            context=CONTEXT,
        )
        assert aggregate["inventory"]["total"] == len(expected)
        grid = await service.list_listings_from_clickhouse(
            "rent",
            area="Jumeirah Village Circle",
            bedrooms="1",
            price_basis="annual",
            **filters,
        )
        assert {row.listing_id for row in grid.listings} == expected
        assert grid.filters.price_min == 10_000.01
        assert grid.filters.price_max == 120_000.13


async def test_price_boundary_listing_age_applies_the_same_strict_limit(inventory):
    for inclusive, expected in [(True, ["old"]), (False, [])]:
        result = await compare_listing_age(
            ListingAgeRequest(
                location="Dubai Marina",
                bedrooms="2",
                price_min=1_000_000,
                price_max=1_500_000,
                price_max_inclusive=inclusive,
            ),
            context=CONTEXT,
        )
        assert [row["listing_id"] for row in result["older_listings"]] == expected
