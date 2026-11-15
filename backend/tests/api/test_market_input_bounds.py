"""Market endpoints reject out-of-range input with 422 instead of a 500 or a silent zero.

Each case was reproduced against the live API on 2026-11-15: an offset past Int32 returned a bare
500, a timeframe past Int32 returned total 0, NaN/inf bands were accepted, market-trend days past
the warehouse's date range returned a 500 and the area list accepted any limit and sort.
"""

from unittest.mock import AsyncMock

import pytest

TRANSACTION_LISTS = ("/api/v1/transactions/sales", "/api/v1/transactions/rentals")
FILTER_OPTIONS = ("/api/v1/filters/sales", "/api/v1/filters/rentals")
EXPORTS = ("/api/v1/transactions/sales/export", "/api/v1/transactions/rentals/export")


@pytest.mark.parametrize("path", TRANSACTION_LISTS)
@pytest.mark.parametrize(
    "query",
    [
        "offset=2147483648",  # past Int32: was a bare 500
        "offset=1000001",
        "offset=-1",
        "limit=0",
        "limit=1001",
    ],
)
async def test_transaction_pages_reject_out_of_range_paging(client, path, query):
    response = await client.get(f"{path}?{query}")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("path", TRANSACTION_LISTS + FILTER_OPTIONS + EXPORTS)
@pytest.mark.parametrize(
    "query",
    [
        "timeframe_days=99999999999",  # past Int32: was a 200 with total 0
        "timeframe_days=0",
        "timeframe_days=-5",
        "timeframe_days=10001",
        "size_min=nan",
        "size_max=inf",
        "size_min=-1",
        "size_max=1e400",
        "location=" + "x" * 201,
        "building=" + "x" * 201,
        "project=" + "x" * 201,
    ],
)
async def test_transaction_filters_reject_unbounded_values(client, path, query):
    response = await client.get(f"{path}?{query}")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "path", ("/api/v1/transactions/sales", "/api/v1/filters/sales", EXPORTS[0])
)
@pytest.mark.parametrize(
    "query",
    [
        "price_min=inf",
        "price_max=nan",
        "price_min=-1",
        "price_per_sqft_min=nan",
        "price_per_sqft_max=1e400",
    ],
)
async def test_sales_price_bands_reject_non_finite_and_negative_values(client, path, query):
    response = await client.get(f"{path}?{query}")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "path", ("/api/v1/transactions/rentals", "/api/v1/filters/rentals", EXPORTS[1])
)
@pytest.mark.parametrize("query", ["rent_min=nan", "rent_max=inf", "rent_min=-1"])
async def test_rent_bands_reject_non_finite_and_negative_values(client, path, query):
    response = await client.get(f"{path}?{query}")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    ("path", "name"),
    [(EXPORTS[0], "transaction_ids"), (EXPORTS[1], "contract_ids")],
)
async def test_selected_row_exports_cap_the_number_of_ids(client, path, name):
    too_many = ",".join(f"ID-{index}" for index in range(1001))

    response = await client.get(path, params={name: too_many, "format": "csv"})

    assert response.status_code == 422, response.text


async def test_transaction_list_accepts_the_largest_supported_page(client, monkeypatch):
    fetch = AsyncMock(return_value={"transactions": [], "total": 0, "limit": 1000, "offset": 0})
    monkeypatch.setattr("app.transaction.router.fetch_sales_transactions", fetch)
    monkeypatch.setattr("app.core.decorators.cache.get", AsyncMock(return_value=None))
    monkeypatch.setattr("app.core.decorators.cache.set", AsyncMock())

    response = await client.get(
        "/api/v1/transactions/sales?limit=1000&offset=1000000&timeframe_days=10000"
        "&price_min=0&size_max=100000000"
    )

    assert response.status_code == 200, response.text
    filters, limit, offset = fetch.await_args.args
    assert (limit, offset, filters.timeframe_days) == (1000, 1_000_000, 10_000)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/analytics/market-trend?days=99999999",  # was a 500
        "/api/v1/analytics/market-trend?days=0",
        "/api/v1/analytics/market-trend?days=-30",
        "/api/v1/analytics/sales?timeframe_days=-1",
        "/api/v1/analytics/sales?timeframe_days=99999999999",
        "/api/v1/analytics/sales?start_date=1900-01-01",  # aggregated every record
        "/api/v1/analytics/sales?end_date=2200-01-01",
        "/api/v1/analytics/sales?start_date=2026-02-01&end_date=2026-01-01",
        "/api/v1/analytics/rentals?timeframe_days=0",
        "/api/v1/analytics/rentals?start_date=1900-01-01",
        "/api/v1/analytics/rentals?start_date=2026-02-01&end_date=2026-01-01",
        "/api/v1/analytics/project/trends?days=0",
        "/api/v1/analytics/project/trends?days=99999999",
        "/api/v1/analytics/project/forecast?days=-1",
        "/api/v1/analytics/project/forecast?days=99999999",
    ],
)
async def test_analytics_windows_reject_out_of_range_days_and_dates(client, path):
    response = await client.get(path)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "query",
    [
        "limit=100000",
        "limit=0",
        "offset=-1",
        "offset=2147483648",
        "sort_by=units;DROP",
        "sort_by=unknown",
        "search=" + "x" * 121,
    ],
)
async def test_area_list_rejects_unbounded_paging_and_unknown_sorts(client, query):
    response = await client.get(f"/api/v1/areas?{query}")

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "query",
    [
        "limit=5000",  # no viewport or area: every plot in Dubai, 6.7 MB
        "west=55.1&south=25.1&limit=500",  # half a viewport
        "west=55.3&south=25.1&east=55.1&north=25.3",  # west of east
        "west=54.0&south=24.0&east=57.0&north=26.0",  # a whole-emirate viewport
        "west=55.1&south=25.1&east=55.2&north=25.2&limit=2501",
        "area=" + "x" * 121,
    ],
)
async def test_dda_plots_require_a_bounded_viewport_or_an_area(client, query):
    response = await client.get(f"/api/v1/projects/dda-plots?{query}")

    assert response.status_code == 422, response.text


async def test_building_pins_cap_matches_what_the_map_requests(client):
    response = await client.get(
        "/api/v1/projects/radar/building-pins?west=55.1&south=25.1&east=55.2&north=25.2&limit=5001"
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("query", ["limit=0", "limit=1001", "offset=-1", "offset=100001"])
async def test_upcoming_projects_rejects_out_of_range_paging(client, query):
    response = await client.get(f"/api/v1/supply/upcoming-projects?{query}")

    assert response.status_code == 422, response.text
