"""Deterministic DDA silver assets for phase 1 entity resolution."""

from __future__ import annotations

from dagster import AssetIn, MaterializeResult, asset

from holocron.resources.clickhouse import ClickHouseResource
from holocron.transforms.dda_entities import (
    DDA_PLOT_SILVER_COLUMNS,
    DDA_PROJECT_AREA_SILVER_COLUMNS,
    DDA_SUBPROJECT_AREA_SILVER_COLUMNS,
    PLOT_NUMBER_RAW_IDX,
    dda_plot_silver_row,
    dda_project_area_silver_row,
    dda_subproject_area_silver_row,
)


@asset(
    name="dda_plot_silver",
    group_name="dda",
    tags={
        "provider": "dda",
        "dataset": "dda_planning_layers",
        "asset_type": "silver",
        "table": "dda_plot_silver",
    },
    ins={"dda_land_plots_bronze": AssetIn(key="dda_land_plots")},
    description=(
        "Build deterministic DDA plot silver rows with normalized plot, project, area, and "
        "developer fields plus preserved geometry context."
    ),
)
def dda_plot_silver(
    context,
    dda_land_plots_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, dda_land_plots_bronze

    columns, result_rows = clickhouse.query_rows(
        """
        SELECT
            plot_number, old_numbers, project_name, community_name, master_developer,
            plot_area_sqm, max_gfa_sqm, max_height, land_use, coordinates
        FROM dda_land_plots
        """
    )
    rows = [dict(zip(columns, row, strict=False)) for row in result_rows]

    silver_rows: list[tuple] = []
    for row in rows:
        silver_rows.append(dda_plot_silver_row(row))

    silver_rows.sort(key=lambda item: item[PLOT_NUMBER_RAW_IDX])
    row_count = clickhouse.replace_table_rows(
        table="dda_plot_silver",
        rows=silver_rows,
        column_names=DDA_PLOT_SILVER_COLUMNS,
        staging_suffix="dda_plot_silver",
    )
    return MaterializeResult(metadata={"row_count": row_count, "bronze_row_count": len(rows)})


@asset(
    name="dda_project_area_silver",
    group_name="dda",
    tags={
        "provider": "dda",
        "dataset": "dda_planning_layers",
        "asset_type": "silver",
        "table": "dda_project_area_silver",
    },
    ins={"dda_project_areas_bronze": AssetIn(key="dda_project_areas")},
    description=(
        "Build deterministic DDA project-area silver rows with normalized names and preserved "
        "WGS84 project geometry."
    ),
)
def dda_project_area_silver(
    context,
    dda_project_areas_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, dda_project_areas_bronze

    columns, result_rows = clickhouse.query_rows(
        "SELECT object_id, project_name, rings FROM dda_project_areas"
    )
    rows = [dict(zip(columns, row, strict=False)) for row in result_rows]

    silver_rows: list[tuple] = []
    for row in rows:
        silver_rows.append(dda_project_area_silver_row(row))

    silver_rows.sort(key=lambda item: item[2])
    row_count = clickhouse.replace_table_rows(
        table="dda_project_area_silver",
        rows=silver_rows,
        column_names=DDA_PROJECT_AREA_SILVER_COLUMNS,
        staging_suffix="dda_project_area_silver",
    )
    return MaterializeResult(metadata={"row_count": row_count, "bronze_row_count": len(rows)})


@asset(
    name="dda_subproject_area_silver",
    group_name="dda",
    tags={
        "provider": "dda",
        "dataset": "dda_planning_layers",
        "asset_type": "silver",
        "table": "dda_subproject_area_silver",
    },
    ins={"dda_subproject_areas_bronze": AssetIn(key="dda_subproject_areas")},
    description=(
        "Build deterministic DDA subproject-area silver rows with normalized project, "
        "subproject, developer, and plot identifiers."
    ),
)
def dda_subproject_area_silver(
    context,
    dda_subproject_areas_bronze,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    del context, dda_subproject_areas_bronze

    columns, result_rows = clickhouse.query_rows(
        """
        SELECT
            object_id, project_id, project_name, entity_name, developer_name,
            master_project_name, original_plot_number, rings
        FROM dda_subproject_areas
        """
    )
    rows = [dict(zip(columns, row, strict=False)) for row in result_rows]

    silver_rows: list[tuple] = []
    for row in rows:
        silver_rows.append(dda_subproject_area_silver_row(row))

    silver_rows.sort(key=lambda item: item[2])
    row_count = clickhouse.replace_table_rows(
        table="dda_subproject_area_silver",
        rows=silver_rows,
        column_names=DDA_SUBPROJECT_AREA_SILVER_COLUMNS,
        staging_suffix="dda_subproject_area_silver",
    )
    return MaterializeResult(metadata={"row_count": row_count, "bronze_row_count": len(rows)})
