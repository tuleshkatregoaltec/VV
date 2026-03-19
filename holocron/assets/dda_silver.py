"""Deterministic DDA silver assets for phase 1 entity resolution."""

from __future__ import annotations

from dagster import AssetIn, MaterializeResult, asset

from holocron.lib.entity_normalization import (
    dedupe_preserve_order,
    normalize_identifier,
    normalize_text,
    parse_json_list,
    to_json,
    token_bag,
)
from holocron.resources.clickhouse import ClickHouseResource

DDA_PLOT_SILVER_COLUMNS = [
    "source_name",
    "source_table",
    "source_record_key",
    "source_system_id",
    "entity_hint_type",
    "relationship_hint_type",
    "raw_display_name",
    "normalized_display_name",
    "normalized_tokens_json",
    "plot_number_raw",
    "plot_number_normalized",
    "old_plot_numbers_raw",
    "old_plot_numbers_normalized_json",
    "project_name_raw",
    "project_name_normalized",
    "area_name_raw",
    "area_name_normalized",
    "developer_name_raw",
    "developer_name_normalized",
    "plot_area_sqm",
    "max_gfa_sqm",
    "max_height_raw",
    "land_use_json",
    "geometry_json",
    "lat",
    "lng",
    "source_confidence_notes",
]

DDA_PROJECT_AREA_SILVER_COLUMNS = [
    "source_name",
    "source_table",
    "source_record_key",
    "source_system_id",
    "entity_hint_type",
    "relationship_hint_type",
    "raw_display_name",
    "normalized_display_name",
    "normalized_tokens_json",
    "project_name_raw",
    "project_name_normalized",
    "geometry_json",
    "lat",
    "lng",
    "source_confidence_notes",
]

DDA_SUBPROJECT_AREA_SILVER_COLUMNS = [
    "source_name",
    "source_table",
    "source_record_key",
    "source_system_id",
    "entity_hint_type",
    "relationship_hint_type",
    "raw_display_name",
    "normalized_display_name",
    "normalized_tokens_json",
    "project_id_raw",
    "project_id_normalized",
    "project_name_raw",
    "project_name_normalized",
    "subproject_name_raw",
    "subproject_name_normalized",
    "developer_name_raw",
    "developer_name_normalized",
    "master_project_name_raw",
    "master_project_name_normalized",
    "original_plot_number_raw",
    "original_plot_number_normalized",
    "geometry_json",
    "lat",
    "lng",
    "source_confidence_notes",
]


_PLOT_NUMBER_RAW_IDX = DDA_PLOT_SILVER_COLUMNS.index("plot_number_raw")


def _parse_points(raw_list: list) -> list[list[float]]:
    points: list[list[float]] = []
    for point in raw_list:
        if not isinstance(point, list) or len(point) != 2:
            continue
        try:
            points.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            continue
    return points


def _parse_plot_coordinates(value: str) -> list[list[float]]:
    return _parse_points(parse_json_list(value))


def _parse_ring_coordinates(value: str) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    for ring in parse_json_list(value):
        if not isinstance(ring, list):
            continue
        normalized_ring = _parse_points(ring)
        if normalized_ring:
            rings.append(normalized_ring)
    return rings


def _centroid_from_rings(rings: list[list[list[float]]]) -> tuple[float | None, float | None]:
    points = [point for ring in rings for point in ring]
    if not points:
        return None, None
    lng = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)
    return lat, lng


def _normalized_identifier_list(value: str) -> list[str]:
    parts = [part.strip() for part in str(value or "").split(",")]
    normalized = [n for part in parts if (n := normalize_identifier(part))]
    return dedupe_preserve_order(normalized)


def _json_array_string(value: str) -> str:
    return to_json(parse_json_list(value))


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
        coordinates = _parse_plot_coordinates(str(row["coordinates"] or ""))
        silver_rows.append(
            (
                "dda",
                "dda_land_plots",
                str(row["plot_number"] or ""),
                str(row["plot_number"] or ""),
                "plot",
                "plot_in_project_area",
                str(row["plot_number"] or ""),
                normalize_text(row["plot_number"]),
                to_json(token_bag(row["plot_number"])),
                str(row["plot_number"] or ""),
                normalize_identifier(row["plot_number"]),
                str(row["old_numbers"] or ""),
                to_json(_normalized_identifier_list(str(row["old_numbers"] or ""))),
                str(row["project_name"] or ""),
                normalize_text(row["project_name"]),
                str(row["community_name"] or ""),
                normalize_text(row["community_name"]),
                str(row["master_developer"] or ""),
                normalize_text(row["master_developer"]),
                float(row["plot_area_sqm"] or 0),
                float(row["max_gfa_sqm"] or 0),
                str(row["max_height"] or ""),
                _json_array_string(str(row["land_use"] or "")),
                to_json(coordinates),
                None,
                None,
                (
                    "DDA plot geometry preserved in source UTM coordinates; no lat/lng conversion "
                    "performed at silver stage."
                ),
            )
        )

    silver_rows.sort(key=lambda item: item[_PLOT_NUMBER_RAW_IDX])
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
        rings = _parse_ring_coordinates(str(row["rings"] or ""))
        lat, lng = _centroid_from_rings(rings)
        silver_rows.append(
            (
                "dda",
                "dda_project_areas",
                str(row["object_id"]),
                str(row["object_id"]),
                "project",
                "project_area",
                str(row["project_name"] or ""),
                normalize_text(row["project_name"]),
                to_json(token_bag(row["project_name"])),
                str(row["project_name"] or ""),
                normalize_text(row["project_name"]),
                to_json(rings),
                lat,
                lng,
                "DDA project area geometry is preserved in WGS84 ring coordinates.",
            )
        )

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
        rings = _parse_ring_coordinates(str(row["rings"] or ""))
        lat, lng = _centroid_from_rings(rings)
        silver_rows.append(
            (
                "dda",
                "dda_subproject_areas",
                str(row["object_id"]),
                str(row["object_id"]),
                "subproject",
                "subproject_in_project",
                str(row["entity_name"] or row["project_name"] or ""),
                normalize_text(row["entity_name"] or row["project_name"]),
                to_json(token_bag(row["entity_name"] or row["project_name"])),
                str(row["project_id"] or ""),
                normalize_identifier(row["project_id"]),
                str(row["project_name"] or ""),
                normalize_text(row["project_name"]),
                str(row["entity_name"] or ""),
                normalize_text(row["entity_name"]),
                str(row["developer_name"] or ""),
                normalize_text(row["developer_name"]),
                str(row["master_project_name"] or ""),
                normalize_text(row["master_project_name"]),
                str(row["original_plot_number"] or ""),
                normalize_identifier(row["original_plot_number"]),
                to_json(rings),
                lat,
                lng,
                "DDA subproject area geometry is preserved in WGS84 ring coordinates.",
            )
        )

    silver_rows.sort(key=lambda item: item[2])
    row_count = clickhouse.replace_table_rows(
        table="dda_subproject_area_silver",
        rows=silver_rows,
        column_names=DDA_SUBPROJECT_AREA_SILVER_COLUMNS,
        staging_suffix="dda_subproject_area_silver",
    )
    return MaterializeResult(metadata={"row_count": row_count, "bronze_row_count": len(rows)})
