"""A filter that matches no records gives an empty summary, never an HTTP 500."""

import json
import math
from datetime import date

from app.analytics import queries, service

# ClickHouse answers an aggregate over no rows with one row: a zero count and NaN averages,
# which JSON cannot encode.
NAN = math.nan
PERIOD = {"start_date": date(2025, 10, 1), "end_date": date(2026, 9, 30)}


async def nothing(*args, **kwargs):
    return []


async def test_sales_summary_of_no_sales_is_empty(monkeypatch):
    async def no_sales(*args, **kwargs):
        return [{"transaction_count": 0, "median_price": NAN, "avg_price": NAN, "total_volume": 0}]

    monkeypatch.setattr(queries, "fetch_sales_summary", no_sales)
    monkeypatch.setattr(queries, "fetch_sales_trends", nothing)
    monkeypatch.setattr(queries, "fetch_sales_breakdown", nothing)

    response = await service.get_sales_analytics(master_project="No Such Place", **PERIOD)

    assert response.summary.transaction_count == 0
    assert response.trends == []
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


async def test_rentals_summary_of_no_leases_is_empty(monkeypatch):
    async def no_leases(*args, **kwargs):
        return [{"contract_count": 0, "median_rent": NAN, "avg_rent": NAN, "total_annual_value": 0}]

    monkeypatch.setattr(queries, "fetch_rentals_summary", no_leases)
    monkeypatch.setattr(queries, "fetch_rentals_trends", nothing)
    monkeypatch.setattr(queries, "fetch_rentals_breakdown", nothing)

    response = await service.get_rental_analytics(master_project="No Such Place", **PERIOD)

    assert response.summary.contract_count == 0
    assert response.trends == []
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


async def test_market_trend_change_of_a_period_without_sizes_is_empty(monkeypatch):
    """30 days of whole-building sales: none has a size, so the period has no median price per
    sq ft (NULL), and an empty previous period has no average (NaN). The change is unknown, not a
    500."""

    async def trend(*args, **kwargs):
        return [{"period": date(2026, 9, 20), "transaction_count": 1, "avg_price": 5e7,
                 "avg_price_sqft": None}]  # fmt: skip

    summaries = iter(
        [
            [{"transaction_count": 1, "avg_price": 5e7, "median_price_per_sqft": None}],
            [{"transaction_count": 0, "avg_price": NAN, "median_price_per_sqft": None}],
        ]
    )

    async def summary(*args, **kwargs):
        return next(summaries)

    monkeypatch.setattr(queries, "fetch_price_trends", trend)
    monkeypatch.setattr(queries, "fetch_sales_summary", summary)

    response = await service.get_market_trend(days=30, market_type="bulk_building")

    assert response.total_transactions == 1
    assert (response.avg_price_change_pct, response.avg_price_sqft_change_pct) == (None, None)
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


async def test_project_without_sales_or_leases_has_no_figures(monkeypatch):
    """Compare opens on projects such as off-plan launches with no sale or lease yet: their
    summary and price distribution are empty, not an HTTP 500 that breaks the page."""

    async def rows(*args, **kwargs):
        return []

    async def no_sales(*args, **kwargs):
        return [{"transaction_count": 0, "total_volume": 0, "avg_price": NAN,
                 "avg_price_sqft": NAN, "median_price": NAN}]  # fmt: skip

    async def no_leases(*args, **kwargs):
        return [{"contract_count": 0, "total_annual_value": 0, "median_annual_rent": NAN,
                 "median_rent_sqft": NAN}]  # fmt: skip

    async def all_rooms_of_no_sales(*args, **kwargs):
        statistics = ("mean_price", "std_price", "log_mean_price", "log_std_price", "p05_price",
                      "p25_price", "p50_price", "p75_price", "p95_price", "mean_price_sqft",
                      "std_price_sqft")  # fmt: skip
        return [{"rooms_en": "__all__", "sale_count": 0, **dict.fromkeys(statistics, NAN)}]

    # Nor has the hierarchy a row for it (no records, no place in it yet).
    for name in dir(queries):
        if name.startswith(("fetch_project_", "fetch_scope_")):
            monkeypatch.setattr(queries, name, rows)
    monkeypatch.setattr(queries, "fetch_project_sales_summary", no_sales)
    monkeypatch.setattr(queries, "fetch_project_rentals_summary", no_leases)
    monkeypatch.setattr(queries, "fetch_project_price_distribution", all_rooms_of_no_sales)

    async def empty_bundle(*args, **kwargs):
        return (await no_sales(), await no_sales(), [], [], [], [], [])

    monkeypatch.setattr(queries, "fetch_project_sales_bundle", empty_bundle)
    summary = await service.get_project_summary(project_name="1wood", filter_type="project")
    distribution = await service.get_project_price_distribution(project_name="1wood")

    assert (summary.sales.transaction_count, summary.sales.avg_price) == (0, 0)
    assert (summary.rentals.contract_count, summary.rentals.median_annual_rent) == (0, 0)
    assert distribution.all is None
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)
    json.dumps(distribution.model_dump(mode="json"), allow_nan=False)
