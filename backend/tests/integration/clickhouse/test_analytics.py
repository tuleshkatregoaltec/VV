from app.analytics.queries import project_sales_summary
from app.clickhouse.client import query


async def test_sales_summary_applies_residential_and_project_scope_in_clickhouse(warehouse):
    await warehouse.command("""
        CREATE TABLE ch_transactions (
            project_name_en String, master_project_en String,
            trans_group_en String, property_type_en String,
            property_usage_en String, actual_worth Decimal(18, 2),
            meter_sale_price Decimal(18, 2), reg_type_en String
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
    )
    rows = await query(project_sales_summary("project"), {"project_name": "Tower A"})
    assert rows[0]["transaction_count"] == 2
    assert rows[0]["total_volume"] == 4000000
    assert rows[0]["avg_price"] == 2000000
    market = await query(project_sales_summary("market"))
    assert market[0]["transaction_count"] == 3
