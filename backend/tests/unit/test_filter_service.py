from unittest.mock import AsyncMock, patch

from app.transaction.facets import get_rental_filter_options, get_sales_filter_options
from app.transaction.models import RentalFilters, SalesFilters


async def test_sales_options_come_from_dxbi_in_one_scan_under_every_filter():
    mock_query = AsyncMock(
        return_value=[
            {
                "property_type_options": ["Villa", " Apartment "],
                "bedroom_options": ["2 Beds", "10 Beds", "Studio", "1 Bed", ""],
                "status_options": ["Ready", "Off-Plan"],
                "location_options": ["dubai Hills Estate", "Downtown Dubai"],
                "building_options": [" Tower B ", "Tower A"],
            }
        ]
    )

    with patch("app.transaction.queries.query", new=mock_query):
        result = await get_sales_filter_options(
            SalesFilters(
                property_usage="Residential",
                property_type="Apartment",
                bedrooms="2 Beds",
                status="Ready",
                location="Downtown Dubai",
                building="Tower A",
                timeframe_days=30,
                size_min=1000,
                size_max=2000,
                price_min=1_000_000,
                price_max=2_000_000,
                price_per_sqft_min=2_000,
                price_per_sqft_max=3_000,
            )
        )

    assert result.property_types == ["Apartment", "Villa"]
    # Studio first, then counts in numeric order (10 after 2), not alphabetically.
    assert result.bedrooms == ["Studio", "1 Bed", "2 Beds", "10 Beds"]
    assert result.statuses == ["Off-Plan", "Ready"]
    assert result.locations == ["Downtown Dubai", "dubai Hills Estate"]
    assert result.buildings == ["Tower A", "Tower B"]
    assert result.contract_types == []

    assert mock_query.await_count == 1
    sql, params = mock_query.await_args.args
    assert "FROM dxbi_sales_unit_events FINAL" in sql
    assert "ch_transactions" not in sql
    # The date window applies before de-duplication; bands are [min, max).
    assert "transaction_date > today() - {timeframe_days:Int32}" in sql
    assert "size_sqft >= {size_min:Float64}" in sql and "size_sqft < {size_max:Float64}" in sql
    assert "price_per_sqft < {price_per_sqft_max:Float64}" in sql
    assert params == {
        "timeframe_days": 30,
        "property_usage": "Residential",
        "property_type": "Apartment",
        "bedrooms": "2 Beds",
        "status": "Ready",
        "location": "Downtown Dubai",
        "building": "Tower A",
        "size_min": 1000,
        "size_max": 2000,
        "price_min": 1_000_000,
        "price_max": 2_000_000,
        "price_per_sqft_min": 2_000,
        "price_per_sqft_max": 3_000,
    }


async def test_rental_options_come_from_dxbi_in_one_scan_under_every_filter():
    mock_query = AsyncMock(
        return_value=[
            {
                "property_type_options": ["Commercial", "Apartment"],
                "bedroom_options": ["3 Beds", "Studio"],
                "contract_type_options": ["Renewed", "New"],
                "location_options": ["Dubai Marina", " JVC "],
                "building_options": [],
            }
        ]
    )

    with patch("app.transaction.queries.query", new=mock_query):
        result = await get_rental_filter_options(
            RentalFilters(
                property_usage="Residential",
                contract_type="Renewed",
                location="Dubai Marina",
                timeframe_days=180,
                size_min=500,
                size_max=1000,
                rent_min=50_000,
                rent_max=100_000,
            )
        )

    assert result.property_types == ["Apartment", "Commercial"]
    assert result.bedrooms == ["Studio", "3 Beds"]
    assert result.contract_types == ["New", "Renewed"]
    assert result.locations == ["Dubai Marina", "JVC"]
    assert result.statuses == []

    sql, params = mock_query.await_args.args
    assert "FROM dxbi_rental_events FINAL" in sql
    assert "ch_rent_contracts" not in sql
    assert "lease_start > today() - {timeframe_days:Int32} AND lease_start <= today()" in sql
    assert "annual_rent_aed < {rent_max:Float64}" in sql
    assert params == {
        "timeframe_days": 180,
        "property_usage": "Residential",
        "contract_type": "Renewed",
        "location": "Dubai Marina",
        "size_min": 500,
        "size_max": 1000,
        "rent_min": 50_000,
        "rent_max": 100_000,
    }
