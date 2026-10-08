"""A filter that matches no records gives an empty summary, never an HTTP 500."""

import json
import math
from datetime import date

from app.analytics import queries, service

# ClickHouse answers an aggregate over no rows with one row: a zero count and NaN averages,
# which JSON cannot encode.
NAN = math.nan
PERIOD = {"start_date": date(2025, 10, 1), "end_date": date(2026, 9, 30)}


async def test_sales_summary_of_no_sales_is_empty(monkeypatch):
    async def no_sales(*args, **kwargs):
        return [{"transaction_count": 0, "median_price": NAN, "avg_price": NAN, "total_volume": 0}]

    monkeypatch.setattr(queries, "fetch_sales_summary", no_sales)

    response = await service.get_sales_analytics(master_project="No Such Place", **PERIOD)

    assert response.summary.transaction_count == 0
    assert response.trends == []
    json.dumps(response.model_dump(mode="json"), allow_nan=False)


async def test_rentals_summary_of_no_leases_is_empty(monkeypatch):
    async def no_leases(*args, **kwargs):
        return [{"contract_count": 0, "median_rent": NAN, "avg_rent": NAN, "total_annual_value": 0}]

    monkeypatch.setattr(queries, "fetch_rentals_summary", no_leases)

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
