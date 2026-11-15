"""The /analytics/sales and /analytics/rentals responses are complete, or they fail loudly.

They used to answer with the summary only: trends and every breakdown were always empty and the
period-on-period changes always null, so the dashboard modals drew empty charts. A query failure
was logged and answered as a 200 with zeros, so an outage read as "no sales".
"""

from datetime import date

import pytest
from fastapi import HTTPException

from app.analytics import queries, service

PERIOD = {"start_date": date(2026, 1, 10), "end_date": date(2026, 3, 20)}


def _sales_summary(count, volume):
    return [{"transaction_count": count, "total_volume": volume, "avg_price": volume / count,
             "median_price": 1.5e6, "avg_price_sqft": 1500.0, "min_price": 5e4,
             "max_price": 9e6}]  # fmt: skip


@pytest.fixture
def sales_queries(monkeypatch):
    calls: dict[str, list] = {"summary": [], "trend": [], "breakdown": []}

    async def summary(parameters, **kwargs):
        calls["summary"].append(parameters)
        # The current period first, then the equal period just before it.
        return _sales_summary(100, 2e8) if len(calls["summary"]) == 1 else _sales_summary(80, 1.6e8)

    async def trends(parameters, *, interval, **kwargs):
        calls["trend"].append(interval)
        return [
            {"period": date(2026, 1, 4), "count": 10, "total_value": 2e7, "avg_value": 2e6,
             "avg_sqft": 1400.0},
            {"period": date(2026, 3, 15), "count": 5, "total_value": 1e7, "avg_value": 2e6,
             "avg_sqft": None},
        ]  # fmt: skip

    async def breakdown(parameters, dimension, **kwargs):
        calls["breakdown"].append(dimension)
        return [
            {"dimension_value": f"{dimension} a", "transaction_count": 75, "total_volume": 1.5e8,
             "avg_price_sqft": 1600.0},
            {"dimension_value": f"{dimension} b", "transaction_count": 25, "total_volume": 5e7,
             "avg_price_sqft": float("nan")},
        ]  # fmt: skip

    monkeypatch.setattr(queries, "fetch_sales_summary", summary)
    monkeypatch.setattr(queries, "fetch_sales_trends", trends)
    monkeypatch.setattr(queries, "fetch_sales_breakdown", breakdown)
    return calls


async def test_sales_response_has_trends_breakdowns_and_changes(sales_queries):
    response = await service.get_sales_analytics(**PERIOD)

    assert [point.count for point in response.trends] == [10, 5]
    assert sorted(sales_queries["breakdown"]) == [
        "master_project",
        "property_type",
        "reg_type",
        "rooms",
    ]
    for name in sales_queries["breakdown"]:
        rows = getattr(response, f"by_{name}")
        assert [row.dimension_value for row in rows] == [f"{name} a", f"{name} b"]
    assert [row.pct_of_total for row in response.by_rooms] == [75.0, 25.0]
    # A group without a sized record has no average per sq ft (not NaN in JSON).
    assert response.by_rooms[1].avg_price_sqft == 0.0
    # 100 sales for 200M against 80 for 160M in the equal period before.
    assert response.summary.count_change_pct == 25.0
    assert response.summary.volume_change_pct == 25.0
    assert response.summary.median_price == 1.5e6


async def test_sales_previous_period_is_the_equal_period_just_before(sales_queries):
    await service.get_sales_analytics(**PERIOD)

    current, previous = sales_queries["summary"]
    assert (current["start_date"], current["end_date"]) == ("2026-01-10", "2026-03-20")
    # 10 Jan to 20 Mar is 70 whole days: so is 1 Nov to 9 Jan, ending the day before.
    assert (previous["start_date"], previous["end_date"]) == ("2025-11-01", "2026-01-09")


async def test_sales_trend_flags_periods_cut_by_the_window(sales_queries):
    response = await service.get_sales_analytics(**PERIOD)

    # 70 days: weekly points. The week of 4 Jan starts before 10 Jan; the week of 15 Mar ends
    # after 20 Mar. Neither is a whole week, so neither compares with a whole one.
    assert sales_queries["trend"] == ["week"]
    assert [point.partial for point in response.trends] == [True, True]


async def test_sales_market_type_echoes_its_usage_not_the_default(sales_queries):
    response = await service.get_sales_analytics(market_type="commercial_units", **PERIOD)

    assert response.market_type == "commercial_units"
    assert response.property_usage == "Commercial"


async def test_sales_query_failure_is_an_error_not_zeros(monkeypatch):
    async def outage(*args, **kwargs):
        raise ConnectionError("ClickHouse is unreachable")

    monkeypatch.setattr(queries, "fetch_sales_summary", outage)

    with pytest.raises(HTTPException) as failure:
        await service.get_sales_analytics(**PERIOD)
    assert failure.value.status_code == 503


async def test_rentals_response_has_trends_breakdowns_and_changes(monkeypatch):
    summaries = iter(
        [
            [{"contract_count": 50, "total_annual_value": 5e6, "avg_rent": 1e5, "median_rent": 9e4,
              "avg_rent_sqft": 100.0, "min_rent": 2e4, "max_rent": 5e5}],
            [{"contract_count": 40, "total_annual_value": 4e6, "avg_rent": 1e5, "median_rent": 9e4,
              "avg_rent_sqft": 100.0, "min_rent": 2e4, "max_rent": 5e5}],
        ]
    )  # fmt: skip

    async def summary(*args, **kwargs):
        return next(summaries)

    async def trends(parameters, *, interval, **kwargs):
        return [{"period": date(2026, 2, 1), "count": 50, "total_value": 5e6, "avg_value": 1e5,
                 "avg_sqft": 100.0}]  # fmt: skip

    async def breakdown(parameters, dimension, **kwargs):
        return [{"dimension_value": "Apartment", "contract_count": 50, "total_annual_value": 5e6,
                 "avg_rent_sqft": 100.0}]  # fmt: skip

    monkeypatch.setattr(queries, "fetch_rentals_summary", summary)
    monkeypatch.setattr(queries, "fetch_rentals_trends", trends)
    monkeypatch.setattr(queries, "fetch_rentals_breakdown", breakdown)

    response = await service.get_rental_analytics(**PERIOD)

    assert [point.count for point in response.trends] == [50]
    assert response.by_property_type[0].pct_of_total == 100.0
    assert response.by_master_project[0].contract_count == 50
    assert response.summary.count_change_pct == 25.0
    assert response.summary.value_change_pct == 25.0
    assert response.summary.median_annual_rent == 9e4


async def test_rentals_query_failure_is_an_error_not_zeros(monkeypatch):
    async def outage(*args, **kwargs):
        raise ConnectionError("ClickHouse is unreachable")

    monkeypatch.setattr(queries, "fetch_rentals_summary", outage)

    with pytest.raises(HTTPException) as failure:
        await service.get_rental_analytics(**PERIOD)
    assert failure.value.status_code == 503


async def test_market_trend_failure_is_an_error_not_an_empty_chart(monkeypatch):
    async def outage(*args, **kwargs):
        raise ConnectionError("ClickHouse is unreachable")

    monkeypatch.setattr(queries, "fetch_price_trends", outage)
    monkeypatch.setattr(queries, "fetch_sales_summary", outage)

    with pytest.raises(HTTPException) as failure:
        await service.get_market_trend(days=365)
    assert failure.value.status_code == 503


async def test_market_trend_flags_the_partial_first_and_last_months(monkeypatch):
    async def trend(*args, **kwargs):
        return [
            {"period": date(2025, 11, 1), "transaction_count": 8486, "avg_price": 2e6,
             "avg_price_sqft": 1500.0},
            {"period": date(2025, 12, 1), "transaction_count": 15000, "avg_price": 2e6,
             "avg_price_sqft": 1500.0},
            {"period": date(2026, 11, 1), "transaction_count": 4683, "avg_price": 2e6,
             "avg_price_sqft": 1500.0},
        ]  # fmt: skip

    async def summary(*args, **kwargs):
        return [{"transaction_count": 1, "avg_price": 2e6, "median_price_per_sqft": 1500.0}]

    monkeypatch.setattr(queries, "fetch_price_trends", trend)
    monkeypatch.setattr(queries, "fetch_sales_summary", summary)
    monkeypatch.setattr(service, "date", _Today(date(2026, 11, 15)))

    response = await service.get_market_trend(days=365)

    assert [point.partial for point in response.data] == [True, False, True]


class _Today:
    """``date`` with a fixed today; other uses pass through."""

    def __init__(self, today: date) -> None:
        self._today = today

    def today(self) -> date:
        return self._today

    def __call__(self, *args):
        return date(*args)

    def __getattr__(self, name):
        return getattr(date, name)


def test_breakdown_and_trend_sql_share_the_summary_filters():
    """A breakdown row or trend point counts the summary's records, split: the same WHERE."""
    filters = dict(
        property_usage="Residential",
        start_date="2026-01-01",
        end_date="2026-03-31",
        master_project="Dubai Marina",
        rooms="1 B/R",
        price_range=(1e6, 2e6),
    )
    where = queries.sales_summary(**filters).split("WHERE", 1)[1].strip()
    assert where in queries.sales_breakdown("rooms", **filters)
    assert where in queries.sales_trends("week", **filters)
    rental = dict(property_usage="Residential", start_date="2026-01-01", end_date="2026-03-31")
    rental_where = queries.rentals_summary(**rental).split("WHERE", 1)[1].strip()
    assert rental_where in queries.rentals_breakdown("master_project", **rental)
    assert rental_where in queries.rentals_trends("month", **rental)


async def test_busiest_masters_share_the_whole_summary_not_each_other(sales_queries, monkeypatch):
    async def top_master(parameters, dimension, **kwargs):
        return [{"dimension_value": "Dubai Marina", "transaction_count": 30, "total_volume": 6e7,
                 "avg_price_sqft": 1600.0}]  # fmt: skip

    monkeypatch.setattr(queries, "fetch_sales_breakdown", top_master)

    response = await service.get_sales_analytics(**PERIOD)

    assert response.by_master_project[0].pct_of_total == 30.0
