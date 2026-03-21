"""Silver assets for Property Finder locations."""

from __future__ import annotations

from dagster import AssetIn, MaterializeResult, asset

from holocron.resources.clickhouse import ClickHouseResource
from holocron.transforms.pf_locations import BRONZE_COLUMNS, SILVER_COLUMNS, build_hierarchy_rows


@asset(
    name="pf_location_hierarchy",
    group_name="propertyfinder",
    tags={
        "provider": "propertyfinder",
        "dataset": "pf_locations",
        "asset_type": "silver",
        "table": "pf_location_hierarchy",
    },
    ins={"pf_locations_bronze": AssetIn(key="pf_locations")},
    description=(
        "Build a cleaned Property Finder location hierarchy from the bronze pf_locations "
        "table, deriving explicit parent/ancestor fields and normalized levels."
    ),
)
def pf_location_hierarchy(
    context,
    pf_locations_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del pf_locations_bronze

    columns, result_rows = clickhouse.query_rows(
        f"SELECT {', '.join(BRONZE_COLUMNS)} FROM pf_locations"
    )
    rows = [dict(zip(columns, row, strict=False)) for row in result_rows]
    silver_rows = build_hierarchy_rows(rows)
    row_count = clickhouse.replace_table_rows(
        table="pf_location_hierarchy",
        rows=silver_rows,
        column_names=SILVER_COLUMNS,
        staging_suffix="pf_location_hierarchy",
    )
    return MaterializeResult(
        metadata={
            "row_count": row_count,
            "bronze_row_count": len(rows),
        }
    )
