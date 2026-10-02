"""The public API and MCP must send the same exact interval to shared listing services."""

from unittest.mock import AsyncMock

import pytest

from app.listings.models import ListingAnalyticsResponse, ListingListResponse


@pytest.mark.parametrize(
    "path,operation,response",
    [
        (
            "",
            "list_listings_from_clickhouse",
            ListingListResponse(mode="sale", total=0, limit=48, offset=0, listings=[]),
        ),
        (
            "/analytics",
            "listing_analytics_from_clickhouse",
            ListingAnalyticsResponse(mode="sale", total=0),
        ),
    ],
)
async def test_listing_api_expresses_exclusive_and_fractional_bounds_without_changing_defaults(
    client, monkeypatch, path, operation, response
):
    query = AsyncMock(return_value=response)
    monkeypatch.setattr(f"app.listings.router.{operation}", query)
    params = {"mode": "sale", "price_min": "1199999.99", "price_max": "1200000.01"}
    assert (await client.get(f"/api/v1/listings{path}", params=params)).status_code == 200
    assert query.call_args.kwargs["price_min_inclusive"] is True
    assert query.call_args.kwargs["price_max_inclusive"] is True
    params |= {"price_min_inclusive": "false", "price_max_inclusive": "false"}
    assert (await client.get(f"/api/v1/listings{path}", params=params)).status_code == 200
    assert query.call_args.kwargs["price_min"] == 1199999.99
    assert query.call_args.kwargs["price_max"] == 1200000.01
    assert query.call_args.kwargs["price_min_inclusive"] is False
    assert query.call_args.kwargs["price_max_inclusive"] is False
    for invalid in ("nan", "inf", "-inf"):
        assert (
            await client.get(f"/api/v1/listings{path}", params={"price_max": invalid})
        ).status_code == 422
    assert query.await_count == 2
