from app.analytics.queries import project_sales_summary
from app.clickhouse.client import query


async def test_sales_summary_applies_residential_and_project_scope_in_clickhouse(warehouse):
    await warehouse.command("""
        CREATE TABLE ch_transactions (
            project_name_en String, master_project_en String,
            trans_group_en String, property_type_en String,
            property_usage_en String, actual_worth Decimal(18, 2),
            meter_sale_price Decimal(18, 2), reg_type_en String,
            property_type String DEFAULT 'Apartment'
        ) ENGINE = MergeTree ORDER BY project_name_en
    """)
    await warehouse.insert(
        "ch_transactions",
        [
            [
                "Tower A",
                "Master A",
                "Sales",
                "Unit",
                "Residential",
                1000000,
                10000,
                "Existing Properties",
            ],
            [
                "Tower A",
                "Master A",
                "Sales",
                "Unit",
                "Residential",
                3000000,
                30000,
                "Existing Properties",
            ],
            [
                "Tower A",
                "Master A",
                "Sales",
                "Unit",
                "Commercial",
                9000000,
                90000,
                "Existing Properties",
            ],
            [
                "Tower B",
                "Master B",
                "Sales",
                "Unit",
                "Residential",
                5000000,
                50000,
                "Existing Properties",
            ],
            [
                "Tower A",
                "Master A",
                "Mortgages",
                "Unit",
                "Residential",
                7000000,
                70000,
                "Existing Properties",
            ],
        ],
        column_names=[
            "project_name_en",
            "master_project_en",
            "trans_group_en",
            "property_type_en",
            "property_usage_en",
            "actual_worth",
            "meter_sale_price",
            "reg_type_en",
        ],
    )
    # A residential plot in the same project: scoped to units and villas, it must not count.
    await warehouse.command(
        "INSERT INTO ch_transactions VALUES "
        "('Tower A', 'Master A', 'Sales', 'Land', 'Residential', 2000000, 20000, "
        "'Existing Properties', 'Plot')"
    )
    rows = await query(project_sales_summary("project"), {"project_name": "Tower A"})
    assert rows[0]["transaction_count"] == 2
    assert rows[0]["total_volume"] == 4000000
    assert rows[0]["avg_price"] == 2000000
    market = await query(project_sales_summary("market"))
    assert market[0]["transaction_count"] == 3


async def test_market_types_select_on_the_uniform_type_and_their_own_group(warehouse):
    """market_type used DLD's labels ('Unit', 'Land') on the served uniform type, which has
    neither, so residential units, commercial units and land returned 0 sales; mortgages and
    gifts returned ordinary sales. DLD registers most villas as 'Building' or against their land,
    and its commercial-usage villas and plots are not commercial units."""
    from datetime import date

    from app.analytics import service

    await warehouse.command("""
        CREATE TABLE ch_transactions (
            trans_group_en String, property_usage_en String, property_type String,
            property_type_en String, actual_worth Float64, meter_sale_price Float64,
            size_sqm Float64, instance_date Date, master_project_en String DEFAULT '',
            location_name String DEFAULT '', rooms_en String DEFAULT '',
            reg_type_en String DEFAULT '', price_bucket String DEFAULT '',
            area_bucket String DEFAULT ''
        ) ENGINE = MergeTree ORDER BY instance_date
    """)
    day = date.today()
    rows = [
        # group, usage, uniform type, DLD type
        ("Sales", "Residential", "Apartment", "Unit"),
        ("Sales", "Residential", "Hotel Apartment", "Unit"),
        ("Sales", "Residential", "Villa", "Building"),
        ("Sales", "Residential", "Townhouse", "Land"),
        ("Sales", "Commercial", "Office", "Unit"),
        ("Sales", "Hospitality", "Apartment", "Unit"),
        ("Sales", "Commercial", "Villa", "Land"),
        ("Sales", "Commercial", "Plot", "Land"),
        ("Sales", "Residential", "Building", "Building"),
        ("Mortgages", "Residential", "Apartment", "Unit"),
        ("Gifts", "Residential", "Villa", "Villa"),
    ]
    await warehouse.insert(
        "ch_transactions",
        [[*row, 1_000_000, 10_000, 100, day] for row in rows],
        column_names=["trans_group_en", "property_usage_en", "property_type", "property_type_en",
                      "actual_worth", "meter_sale_price", "size_sqm", "instance_date"],
    )  # fmt: skip

    async def sold(market_type: str) -> int:
        response = await service.get_sales_analytics(market_type=market_type, timeframe_days=30)
        return response.summary.transaction_count

    assert await sold("residential_units") == 2
    assert await sold("villas") == 3
    assert await sold("commercial_units") == 2
    assert await sold("land") == 1
    assert await sold("bulk_building") == 1
    assert await sold("mortgages") == 1
    assert await sold("gifts") == 1
    trend = await service.get_market_trend(days=30, market_type="villas")
    assert trend.total_transactions == 3


async def test_a_date_range_holds_its_whole_last_day(warehouse):
    """DLD open-data sales carry a registration time (about 30% of a weekday's sales). A range
    ending on a date compared the timestamp with that date's midnight and dropped them."""
    from datetime import date, datetime

    from app.analytics import service

    await warehouse.command("""
        CREATE TABLE ch_transactions (
            trans_group_en String, property_usage_en String, property_type String,
            actual_worth Float64, meter_sale_price Float64, size_sqm Float64,
            instance_date DateTime, master_project_en String DEFAULT '',
            location_name String DEFAULT '', rooms_en String DEFAULT '',
            reg_type_en String DEFAULT '', price_bucket String DEFAULT '',
            area_bucket String DEFAULT ''
        ) ENGINE = MergeTree ORDER BY instance_date
    """)
    await warehouse.insert(
        "ch_transactions",
        [
            ["Sales", "Residential", "Apartment", 1_000_000, 10_000, 100, when]
            for when in (
                datetime(2026, 9, 1, 0, 0),
                datetime(2026, 9, 10, 0, 0),
                datetime(2026, 9, 10, 14, 30),  # registered in the afternoon of the last day
                datetime(2026, 9, 11, 9, 0),
            )
        ],
        column_names=["trans_group_en", "property_usage_en", "property_type", "actual_worth",
                      "meter_sale_price", "size_sqm", "instance_date"],
    )  # fmt: skip

    response = await service.get_sales_analytics(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 10)
    )

    assert response.summary.transaction_count == 3


async def test_bucket_filters_are_half_open_ranges(warehouse):
    """price_bucket and area_bucket filtered on columns the served table does not have: ClickHouse
    failed and the page got 0 sales. rent_bucket was ignored. Each is a half-open range on the
    value, as the Transactions bands are, and a label that reads as none is an error."""
    from datetime import date

    import pytest
    from fastapi import HTTPException

    from app.analytics import service

    await warehouse.command("""
        CREATE TABLE ch_transactions (
            trans_group_en String, property_usage_en String, property_type String,
            actual_worth Float64, meter_sale_price Float64, size_sqm Float64, instance_date Date,
            master_project_en String DEFAULT '', location_name String DEFAULT '',
            rooms_en String DEFAULT '', reg_type_en String DEFAULT ''
        ) ENGINE = MergeTree ORDER BY instance_date
    """)
    await warehouse.command("""
        CREATE TABLE ch_rent_contracts (
            property_usage_en String, property_type String, annual_amount Float64,
            size_sqm Float64, contract_start_date Date, master_project_en String DEFAULT '',
            location_name String DEFAULT ''
        ) ENGINE = MergeTree ORDER BY contract_start_date
    """)
    day = date.today()
    await warehouse.insert(
        "ch_transactions",
        [["Sales", "Residential", "Apartment", price, 10_000, sqm, day]
         for price, sqm in ((999_999, 90), (1_000_000, 93), (1_999_999, 186), (2_000_000, 200))],
        column_names=["trans_group_en", "property_usage_en", "property_type", "actual_worth",
                      "meter_sale_price", "size_sqm", "instance_date"],
    )  # fmt: skip
    await warehouse.insert(
        "ch_rent_contracts",
        [["Residential", "Apartment", rent, 100, day] for rent in (49_999, 50_000, 100_000)],
        column_names=["property_usage_en", "property_type", "annual_amount", "size_sqm",
                      "contract_start_date"],
    )  # fmt: skip

    async def sold(**buckets) -> int:
        response = await service.get_sales_analytics(timeframe_days=30, **buckets)
        return response.summary.transaction_count

    assert await sold(price_bucket="1M-2M") == 2
    assert await sold(price_bucket="<1M") == 1
    assert await sold(price_bucket="2M+") == 1
    assert await sold(area_bucket="1K-2K") == 1  # 93 m² is 1,001 sq ft; 186 m² is 2,002
    rented = await service.get_rental_analytics(timeframe_days=30, rent_bucket="50K-100K")
    assert rented.summary.contract_count == 1
    with pytest.raises(HTTPException) as refused:
        await sold(price_bucket="cheap")
    assert refused.value.status_code == 422
