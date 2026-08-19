import pytest

from app.listings import service
from app.listings.service import MONTHLY_PRICE_EXPR, PRICE_PERIOD_EXPR, _card_from_row, _where_sql


class Row:
    def __init__(self, data):
        self._mapping = data


def test_card_image_count_uses_available_imported_images():
    card = _card_from_row(
        Row(
            {
                "listing_id": "listing-1",
                "listing_mode": "sale",
                "title": "Test listing",
                "images": [
                    {"label": "missing image url"},
                    {"medium_url": "https://example.com/1.jpg"},
                    {"small_url": "https://example.com/2.jpg"},
                ],
                "image_count": 28,
                "agent": {},
                "broker": {},
                "floorplans": [],
            }
        )
    )

    assert card.primary_image_url == "https://example.com/1.jpg"
    assert card.image_count == 2


def test_listing_where_sql_uses_monthly_basis_for_price_filters():
    where, params = _where_sql(
        mode="rent",
        search=None,
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=10_000,
        price_max=20_000,
        price_basis="monthly",
    )

    assert MONTHLY_PRICE_EXPR in where
    assert params["price_min"] == 10_000
    assert params["price_max"] == 20_000


def test_listing_where_sql_can_filter_raw_price_period():
    where, params = _where_sql(
        mode="rent",
        search=None,
        area=None,
        property_type=None,
        bedrooms=None,
        bedrooms_in=None,
        price_min=None,
        price_max=None,
        price_period="Yearly",
    )

    assert f"{PRICE_PERIOD_EXPR} = {{price_period:String}}" in where
    assert params["price_period"] == "yearly"


@pytest.mark.asyncio
async def test_listing_analytics_uses_the_same_available_listing_scope(monkeypatch):
    calls = []

    async def fake_query(sql, params):
        calls.append((sql, params))
        return [
            {
                "total": 12,
                "median_price_aed": 2_000_000,
                "median_price_per_sqft_aed": 2_100.5,
                "verified_count": 9,
                "area_count": 3,
            }
        ]

    monkeypatch.setattr(service, "query", fake_query)
    analytics = await service.listing_analytics_from_clickhouse(
        mode="sale", area="Dubai Marina", bedrooms="2"
    )

    assert analytics.total == 12
    assert analytics.median_price_aed == 2_000_000
    assert analytics.median_price_per_sqft_aed == 2_100.5
    assert analytics.verified_count == 9
    assert analytics.area_count == 3
    assert "is_available = 1" in calls[0][0]
    assert "quantileTDigestIf" in calls[0][0]
    assert calls[0][1]["area"] == "Dubai Marina"
