"""Analytics must not fall back to DLD prices, labels, stock or search entries."""

import json

import pytest
from test_transactions import (  # noqa: F401
    LOADED,
    dxbi,
    lease,
    sale,
)

from app.analytics import queries, service
from app.clickhouse.client import query


async def test_summary_search_and_charts_are_dxbi_only(dxbi, warehouse):  # noqa: F811
    await dxbi(
        sales=[
            sale("a", project_name="DXBI Tower", dld_transaction_number="verified-id"),
            sale("b", project_name="DXBI Tower", unit_number="102", sale_amount_aed=2400000),
            sale("c", project_name="DXBI Tower", unit_number="103", market_status="Offplan"),
            sale("office", project_name="DXBI Tower", property_type="Office"),
        ],
        leases=[
            lease(
                "rent",
                location_name="DXBI Tower, Downtown Dubai",
                building_name="DXBI Tower",
                area_name="Downtown Dubai",
                bedrooms="1 Bed",
                annual_rent_aed=120000,
            )
        ],
    )
    await warehouse.command("""CREATE TABLE market_dxbi_sale_enrichment (
        sale_key String, dxbi_loaded_at DateTime64(3, 'UTC'),
        requested_transaction_number String, match_status String,
        dld_transaction_number String, dld_line_id String, project_name String
    ) ENGINE=Memory""")
    # A fully eligible enrichment patch must still not affect Analytics.
    await warehouse.insert(
        "market_dxbi_sale_enrichment",
        [["a", LOADED, "verified-id", "matched", "verified-id", "dld-line", "DLD Label"]],
        column_names=[
            "sale_key",
            "dxbi_loaded_at",
            "requested_transaction_number",
            "match_status",
            "dld_transaction_number",
            "dld_line_id",
            "project_name",
        ],
    )
    for table in ("ch_transactions", "ch_rent_contracts", "ch_projects", "ch_units"):
        await warehouse.command(f"CREATE TABLE {table} (project_name_en String) ENGINE=Memory")
        await warehouse.insert(table, [["DLD Only"]])
    summary = await service.get_project_summary("DXBI Tower", "project")
    assert summary.sales.transaction_count == 3
    assert summary.sales.total_volume == 5600000
    assert summary.sales.avg_price_sqft == pytest.approx(2333.33)
    assert summary.rentals.contract_count == 1
    assert summary.rentals.median_annual_rent == 120000
    assert summary.unit_composition == []
    assert summary.project.no_of_units is None
    assert summary.project.developer_name is None
    assert {row.rooms for row in summary.by_rooms} == {"1 B/R"}
    assert summary.configuration_analysis[0].avg_unit_size_sqft == pytest.approx(800)
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)
    search = await service.get_project_search("")
    assert {p.name for p in search.projects} == {"DXBI Tower", "Downtown Dubai"}
    trends = await service.get_project_trends("DXBI Tower", 365)
    assert sum(p.transaction_count for p in trends.data) == 3
    distro = await service.get_project_price_distribution("DXBI Tower")
    assert distro.all.sale_count == 3
    assert distro.all.mean_price == pytest.approx(summary.sales.avg_price)
    forecast = await service.get_project_forecast("DXBI Tower", 365)
    assert forecast.data == [] and forecast.delivery_date is None
    rows = await query(queries.project_sales_summary("project"), {"project_name": "DLD Label"})
    assert rows[0]["transaction_count"] == 0


async def test_rental_only_scope_is_searchable_and_empty_sales_are_json_safe(dxbi):  # noqa: F811
    await dxbi(leases=[lease("rental-only")])
    search = await service.get_project_search("Iris")
    assert [(p.name, p.filter_type) for p in search.projects] == [("Iris Blue", "project")]
    children = await service.get_sub_project_list("Dubai Marina")
    assert [(p.name, p.transaction_count) for p in children.sub_projects] == [("Iris Blue", 0)]
    summary = await service.get_project_summary("Iris Blue")
    assert summary.sales.transaction_count == 0
    assert summary.rentals.contract_count == 1
    assert summary.overall_gross_yield_pct is None
    json.dumps(summary.model_dump(mode="json"), allow_nan=False)
