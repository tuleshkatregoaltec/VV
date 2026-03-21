"""Reusable helpers for DDA silver transforms."""

from __future__ import annotations

from holocron.lib.entity_normalization import (
    dedupe_preserve_order,
    normalize_identifier,
    normalize_text,
    parse_json_list,
    to_json,
    token_bag,
)

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

PLOT_NUMBER_RAW_IDX = DDA_PLOT_SILVER_COLUMNS.index("plot_number_raw")


def parse_points(raw_list: list) -> list[list[float]]:
    points: list[list[float]] = []
    for point in raw_list:
        if not isinstance(point, list) or len(point) != 2:
            continue
        try:
            points.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            continue
    return points


def parse_plot_coordinates(value: str) -> list[list[float]]:
    return parse_points(parse_json_list(value))


def parse_ring_coordinates(value: str) -> list[list[list[float]]]:
    rings: list[list[list[float]]] = []
    for ring in parse_json_list(value):
        if not isinstance(ring, list):
            continue
        normalized_ring = parse_points(ring)
        if normalized_ring:
            rings.append(normalized_ring)
    return rings


def centroid_from_rings(rings: list[list[list[float]]]) -> tuple[float | None, float | None]:
    points = [point for ring in rings for point in ring]
    if not points:
        return None, None
    lng = sum(point[0] for point in points) / len(points)
    lat = sum(point[1] for point in points) / len(points)
    return lat, lng


def normalized_identifier_list(value: str) -> list[str]:
    parts = [part.strip() for part in str(value or "").split(",")]
    normalized = [n for part in parts if (n := normalize_identifier(part))]
    return dedupe_preserve_order(normalized)


def json_array_string(value: str) -> str:
    return to_json(parse_json_list(value))


def dda_plot_silver_row(row: dict) -> tuple:
    coordinates = parse_plot_coordinates(str(row["coordinates"] or ""))
    return (
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
        to_json(normalized_identifier_list(str(row["old_numbers"] or ""))),
        str(row["project_name"] or ""),
        normalize_text(row["project_name"]),
        str(row["community_name"] or ""),
        normalize_text(row["community_name"]),
        str(row["master_developer"] or ""),
        normalize_text(row["master_developer"]),
        float(row["plot_area_sqm"] or 0),
        float(row["max_gfa_sqm"] or 0),
        str(row["max_height"] or ""),
        json_array_string(str(row["land_use"] or "")),
        to_json(coordinates),
        None,
        None,
        "DDA plot geometry preserved in source UTM coordinates; no lat/lng conversion performed at silver stage.",
    )


def dda_project_area_silver_row(row: dict) -> tuple:
    rings = parse_ring_coordinates(str(row["rings"] or ""))
    lat, lng = centroid_from_rings(rings)
    return (
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


def dda_subproject_area_silver_row(row: dict) -> tuple:
    rings = parse_ring_coordinates(str(row["rings"] or ""))
    lat, lng = centroid_from_rings(rings)
    return (
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
