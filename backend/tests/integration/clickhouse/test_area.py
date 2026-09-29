import pytest

from app.area.service import get_area_detail, list_areas


async def test_area_filters_sort_and_detail_use_the_same_normalized_name(warehouse):
    await warehouse.command("""CREATE TABLE ch_area_fact (
        area_name_en String, area_id Int32, active_projects UInt32, completed_projects UInt32,
        overdue_projects UInt32, pipeline_units UInt32, units_delivering_next_12_months UInt32,
        active_developers UInt32, avg_completion_pct Float64, avg_delivery_confidence Float64,
        sales_transaction_count_12m UInt32, rental_contract_count_12m UInt32,
        total_sales_volume_12m Float64, median_sale_price Float64, median_annual_rent Float64,
        avg_sale_price_sqm_12m Float64, avg_rent_price_sqm_12m Float64, gross_yield_pct Float64,
        top_developers Array(String), top_master_projects Array(String)
    ) ENGINE = MergeTree ORDER BY area_name_en""")
    await warehouse.insert(
        "ch_area_fact",
        [["Business Bay", 1, 200, 1000000], ["Other Area", 2, 100, 2000000]],
        column_names=["area_name_en", "area_id", "pipeline_units", "total_sales_volume_12m"],
    )
    await warehouse.command("""CREATE TABLE ch_project_fact (
        area_name_en String, project_id Int32, project_name_en String, developer_name String,
        master_project_en String, completion_status String, pipeline_status String,
        no_of_units UInt32, percent_completed Float64, estimated_delivery_confidence Float64,
        total_sales_volume_12m Float64, median_sale_price Float64, median_annual_rent Float64,
        gross_yield_pct Float64
    ) ENGINE = MergeTree ORDER BY project_id""")
    await warehouse.insert(
        "ch_project_fact",
        [["Business Bay", 1, "Tower", "Builder", 200]],
        column_names=[
            "area_name_en",
            "project_id",
            "project_name_en",
            "developer_name",
            "no_of_units",
        ],
    )
    assert [area.area_name for area in (await list_areas(sort_by="volume")).areas] == [
        "Other Area",
        "Business Bay",
    ]
    filtered = await list_areas(search=" business ", limit=1)
    assert (filtered.total, filtered.areas[0].pipeline_units) == (1, 200)
    detail = await get_area_detail("business-bay")
    assert detail.area_name == "Business Bay"
    assert detail.projects[0].project_id == 1
    assert detail.developer_exposure[0].pipeline_units == 200
    with pytest.raises(ValueError, match="Area not found"):
        await get_area_detail("Missing")
