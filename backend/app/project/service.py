"""Project and building services - redesigned for ClickHouse from first principles."""

import asyncio
import json
import logging
import math
import re
import time
from typing import Any, List, Optional

from app.clickhouse.client import query
from app.project.models import (
    BuildingDetailResponse,
    BuildingInfo,
    BuildingUnitType,
    DDAOutlineFeature,
    DDAPlotFeature,
    GeoPin,
    GeoPolygon,
    MasterProjectResponse,
    MasterProjectSummary,
    ProjectDetailResponse,
    ProjectMarketSnapshotResponse,
    ProjectRadarArea,
    ProjectRadarProject,
    ProjectRadarResponse,
    ProjectRadarStats,
    ProjectSearchResult,
    ProjectUnitComposition,
)

logger = logging.getLogger(__name__)

DDA_GEOMETRY_CACHE_TTL_SECONDS = 60 * 60
_dda_geometry_cache: tuple[float, list[dict[str, Any]]] | None = None


def _room_sort_key(rooms: str) -> tuple:
    normalized = rooms.strip()
    if normalized.lower() == "studio":
        return (0, 0, normalized)
    match = re.match(r"^(\d+)", normalized)
    if match:
        return (1, int(match.group(1)), normalized)
    return (2, 0, normalized.lower())


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _land_use_labels(raw: Any, limit: int = 3) -> list[str]:
    if raw in (None, "", []):
        return []

    if isinstance(raw, list):
        labels: list[str] = []
        for item in raw:
            labels.extend(_land_use_labels(item, limit=limit))
            if len(labels) >= limit:
                break
        return labels[:limit]

    if not isinstance(raw, str):
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip()
        return [cleaned] if cleaned else []

    labels = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            label = " ".join(
                str(item.get(key) or "").strip()
                for key in ("type", "use")
                if str(item.get(key) or "").strip()
            )
            if label and label not in labels:
                labels.append(label)
            if len(labels) >= limit:
                break
    return labels


async def list_all_projects() -> List[ProjectSearchResult]:
    """Get all projects with minimal data for client-side search."""
    sql = """
        SELECT
            p.project_id AS project_id,
            p.project_name_en,
            p.area_name_en,
            p.master_project_en,
            COALESCE(NULLIF(d.developer_name_en, ''), p.developer_name) AS developer_name,
            COALESCE(NULLIF(g.centroid_lat, 0), 25.2048) AS latitude,
            COALESCE(NULLIF(g.centroid_lng, 0), 55.2708) AS longitude
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_name = d.developer_name_ar
        LEFT JOIN ch_geo_projects g ON p.project_id = g.project_id
        WHERE p.project_name_en != ''
          AND NOT match(p.project_name_en, '^Project [0-9]')
        ORDER BY p.project_name_en
        LIMIT 5000
    """

    result = await query(sql, {})

    return [
        ProjectSearchResult(
            project_id=p["project_id"],
            project_name=p["project_name_en"],
            area_name=p.get("area_name_en", "Unknown"),
            developer_name=p.get("developer_name") or None,
            master_project_en=p.get("master_project_en") or None,
            latitude=p["latitude"],
            longitude=p["longitude"],
        )
        for p in result
    ]


async def get_project_details(project_id: int) -> Optional[ProjectDetailResponse]:
    """Get full project details including buildings and unit composition."""
    project_sql = """
        SELECT
            p.project_id AS project_id,
            p.project_number,
            p.project_name_en,
            p.master_project_en,
            p.area_id,
            p.area_name_en,
            p.developer_id,
            COALESCE(NULLIF(d1.developer_name_en, ''), p.developer_name) AS developer_name,
            p.master_developer_id,
            COALESCE(NULLIF(d2.developer_name_en, ''), p.master_developer_name) AS master_developer_name,
            p.no_of_buildings,
            p.no_of_units,
            p.no_of_villas,
            p.no_of_lands,
            p.project_start_date,
            p.project_end_date,
            p.completion_date,
            p.percent_completed,
            p.project_status,
            COALESCE(NULLIF(g.centroid_lat, 0), 25.2048) AS latitude,
            COALESCE(NULLIF(g.centroid_lng, 0), 55.2708) AS longitude,
            g.polygon AS area_polygon
        FROM ch_projects p
        LEFT JOIN ch_developers d1 ON p.developer_name = d1.developer_name_ar
        LEFT JOIN ch_developers d2 ON p.master_developer_name = d2.developer_name_ar
        LEFT JOIN ch_geo_projects g ON p.project_id = g.project_id
        WHERE p.project_id = {project_id:Int32}
        LIMIT 1
    """

    project_result = await query(project_sql, {"project_id": project_id})

    if not project_result:
        return None

    project = project_result[0]

    buildings_sql = """
        SELECT property_id, building_number, floors
        FROM ch_buildings
        WHERE project_id = {project_id:Int32}
        ORDER BY building_number
        LIMIT 100
    """

    composition_sql = """
        SELECT
            property_sub_type_en,
            count() as count,
            round(avg(actual_area), 2) as avg_area_sqm
        FROM ch_units
        WHERE project_id = {project_id:Int32}
          AND property_sub_type_en != ''
        GROUP BY property_sub_type_en
        ORDER BY count DESC
    """

    geo_sql = """
        SELECT building_name_en, project_name_en, lat, lng
        FROM ch_geo_buildings
        WHERE project_name_en = {project_name:String}
        ORDER BY building_name_en
    """

    buildings_result, composition_result, geo_result = await asyncio.gather(
        query(buildings_sql, {"project_id": project_id}),
        query(composition_sql, {"project_id": project_id}),
        query(geo_sql, {"project_name": project["project_name_en"]}),
    )

    buildings = [
        BuildingInfo(
            property_id=b["property_id"],
            building_number=b.get("building_number") or None,
            building_name=b.get("building_number") or f"Building {b['property_id']}",
            floors=b.get("floors") or None,
        )
        for b in buildings_result
    ]

    unit_composition: List[ProjectUnitComposition] = []
    total_units = sum(row["count"] for row in composition_result)
    if total_units > 0:
        for row in composition_result:
            unit_composition.append(
                ProjectUnitComposition(
                    property_sub_type=row["property_sub_type_en"],
                    count=row["count"],
                    percentage=round((row["count"] / total_units) * 100, 2),
                    avg_area_sqm=float(row["avg_area_sqm"]) if row["avg_area_sqm"] else None,
                )
            )

    # Build normalized lookup: building name → property_id for geo pin matching
    def _norm(s: str) -> str:
        return "".join(c.lower() for c in s if c.isalnum())

    building_by_norm = {
        _norm(b.building_name or ""): b.property_id for b in buildings if b.building_name
    }

    geo_pins = [
        GeoPin(
            building_name=r["building_name_en"],
            project_name=r["project_name_en"],
            latitude=r["lat"],
            longitude=r["lng"],
            property_id=building_by_norm.get(_norm(r["building_name_en"])) or None,
        )
        for r in geo_result
    ]

    # Derive project center from geo pins when ch_geo_projects has no entry
    proj_lat = float(project["latitude"])
    proj_lng = float(project["longitude"])
    if proj_lat in (0.0, 25.2048) and geo_pins:
        proj_lat = sum(p.latitude for p in geo_pins) / len(geo_pins)
        proj_lng = sum(p.longitude for p in geo_pins) / len(geo_pins)

    raw_polygon = project.get("area_polygon") or []
    area_polygon = GeoPolygon(coordinates=raw_polygon) if raw_polygon else None

    return ProjectDetailResponse(
        project_id=project["project_id"],
        project_name=project["project_name_en"] or f"Project {project['project_id']}",
        project_number=project.get("project_number"),
        master_project_en=project.get("master_project_en") or None,
        area_id=project.get("area_id"),
        area_name=project.get("area_name_en", "Unknown"),
        latitude=proj_lat,
        longitude=proj_lng,
        area_polygon=area_polygon,
        developer_id=project.get("developer_id"),
        developer_name=project.get("developer_name") or None,
        master_developer_id=project.get("master_developer_id"),
        master_developer_name=project.get("master_developer_name") or None,
        no_of_buildings=project.get("no_of_buildings"),
        no_of_units=project.get("no_of_units"),
        no_of_villas=project.get("no_of_villas"),
        no_of_lands=project.get("no_of_lands"),
        project_start_date=project.get("project_start_date"),
        project_end_date=project.get("project_end_date"),
        completion_date=project.get("completion_date"),
        percent_completed=project.get("percent_completed"),
        project_status=project.get("project_status"),
        unit_composition=unit_composition,
        buildings=buildings,
        geo_pins=geo_pins,
    )


async def get_master_project(master_name: str) -> Optional[MasterProjectResponse]:
    """Get aggregated data for a master project and all its sub-projects."""
    sub_projects_sql = """
        SELECT
            p.project_id,
            p.project_name_en,
            p.project_status,
            p.percent_completed,
            p.no_of_buildings,
            p.no_of_units,
            p.area_name_en,
            COALESCE(NULLIF(d.developer_name_en, ''), p.developer_name) AS developer_name
        FROM ch_projects p
        LEFT JOIN ch_developers d ON p.developer_name = d.developer_name_ar
        WHERE p.master_project_en = {name:String}
          AND p.project_name_en != ''
        ORDER BY p.project_name_en
    """
    sub_projects_result = await query(sub_projects_sql, {"name": master_name})

    if not sub_projects_result:
        return None

    project_names = [p["project_name_en"] for p in sub_projects_result]
    project_ids = [p["project_id"] for p in sub_projects_result]
    area_name = sub_projects_result[0].get("area_name_en", "Unknown")
    developer_name = sub_projects_result[0].get("developer_name") or None

    geo_sql = """
        SELECT building_name_en, project_name_en, lat, lng
        FROM ch_geo_buildings
        WHERE project_name_en IN {names:Array(String)}
        ORDER BY project_name_en, building_name_en
    """
    composition_sql = """
        SELECT
            property_sub_type_en,
            count() AS count,
            round(avg(actual_area), 2) AS avg_area_sqm
        FROM ch_units
        WHERE project_id IN {ids:Array(Int32)}
          AND property_sub_type_en != ''
        GROUP BY property_sub_type_en
        ORDER BY count DESC
    """

    geo_result, composition_result = await asyncio.gather(
        query(geo_sql, {"names": project_names}),
        query(composition_sql, {"ids": project_ids}),
    )

    geo_pins = [
        GeoPin(
            building_name=r["building_name_en"],
            project_name=r["project_name_en"],
            latitude=r["lat"],
            longitude=r["lng"],
        )
        for r in geo_result
    ]

    total_units_comp = sum(r["count"] for r in composition_result)
    unit_composition: List[ProjectUnitComposition] = []
    if total_units_comp > 0:
        for row in composition_result:
            unit_composition.append(
                ProjectUnitComposition(
                    property_sub_type=row["property_sub_type_en"],
                    count=row["count"],
                    percentage=round((row["count"] / total_units_comp) * 100, 2),
                    avg_area_sqm=float(row["avg_area_sqm"]) if row["avg_area_sqm"] else None,
                )
            )

    projects = [
        MasterProjectSummary(
            project_id=p["project_id"],
            project_name=p["project_name_en"],
            project_status=p.get("project_status") or None,
            percent_completed=p.get("percent_completed"),
            no_of_buildings=p.get("no_of_buildings"),
            no_of_units=p.get("no_of_units"),
        )
        for p in sub_projects_result
    ]

    total_buildings = sum((p.no_of_buildings or 0) for p in projects)
    total_units = sum((p.no_of_units or 0) for p in projects)

    return MasterProjectResponse(
        master_name=master_name,
        area_name=area_name,
        developer_name=developer_name,
        total_projects=len(projects),
        total_buildings=total_buildings,
        total_units=total_units,
        projects=projects,
        geo_pins=geo_pins,
        unit_composition=unit_composition,
    )


async def get_project_radar(limit: int = 1400) -> ProjectRadarResponse:
    """Return project and area map data for the radar view."""
    project_sql = """
        WITH geo_by_project AS (
            SELECT
                project_name_en,
                avg(lat) AS latitude,
                avg(lng) AS longitude,
                count() AS geo_pin_count
            FROM ch_geo_buildings
            WHERE lat BETWEEN 20 AND 30
              AND lng BETWEEN 50 AND 60
              AND project_name_en != ''
            GROUP BY project_name_en
        )
        SELECT
            f.project_id AS project_id,
            f.project_name_en AS project_name_en,
            f.area_name_en AS area_name_en,
            f.developer_name AS developer_name,
            f.master_project_en AS master_project_en,
            g.latitude AS latitude,
            g.longitude AS longitude,
            g.geo_pin_count AS geo_pin_count,
            f.completion_status AS completion_status,
            f.pipeline_status AS pipeline_status,
            p.project_status AS project_status,
            f.no_of_units AS no_of_units,
            p.no_of_buildings AS no_of_buildings,
            f.percent_completed AS percent_completed,
            f.estimated_delivery_confidence AS estimated_delivery_confidence,
            f.sales_transaction_count_12m AS sales_transaction_count_12m,
            f.rental_contract_count_12m AS rental_contract_count_12m,
            f.total_sales_volume_12m AS total_sales_volume_12m,
            f.median_sale_price AS median_sale_price,
            f.median_annual_rent AS median_annual_rent,
            f.gross_yield_pct AS gross_yield_pct,
            f.avg_sale_price_sqm_12m AS avg_sale_price_sqm_12m,
            f.avg_rent_price_sqm_12m AS avg_rent_price_sqm_12m
        FROM ch_project_fact f
        INNER JOIN ch_projects p ON p.project_id = f.project_id
        INNER JOIN geo_by_project g ON g.project_name_en = f.project_name_en
        WHERE f.project_name_en != ''
        ORDER BY
            (f.pipeline_status = 'delivering_next_12_months') DESC,
            f.no_of_units DESC,
            f.total_sales_volume_12m DESC
        LIMIT {limit:UInt32}
    """

    area_sql = """
        WITH project_geo AS (
            SELECT
                project_name_en,
                avg(lat) AS latitude,
                avg(lng) AS longitude
            FROM ch_geo_buildings
            WHERE lat BETWEEN 20 AND 30
              AND lng BETWEEN 50 AND 60
              AND project_name_en != ''
            GROUP BY project_name_en
        ),
        area_geo AS (
            SELECT
                p.area_name_en,
                avg(g.latitude) AS latitude,
                avg(g.longitude) AS longitude,
                countDistinct(p.project_id) AS mapped_projects
            FROM ch_projects p
            INNER JOIN project_geo g ON g.project_name_en = p.project_name_en
            WHERE p.area_name_en != ''
            GROUP BY p.area_name_en
        ),
        dda_summary AS (
            SELECT
                community_name,
                count() AS dda_plot_count,
                sum(plot_area_sqm) AS dda_total_plot_area_sqm,
                sum(max_gfa_sqm) AS dda_total_gfa_sqm,
                arrayFilter(x -> x != '', topK(5)(land_use)) AS dda_dominant_land_uses
            FROM ch_gis_land_plots FINAL
            WHERE coordinates != ''
              AND community_name != ''
            GROUP BY community_name
        )
        SELECT
            af.area_id AS area_id,
            af.area_name_en AS area_name_en,
            ag.latitude AS latitude,
            ag.longitude AS longitude,
            ifNull(ag.mapped_projects, 0) AS mapped_projects,
            af.active_projects AS active_projects,
            af.completed_projects AS completed_projects,
            af.overdue_projects AS overdue_projects,
            af.pipeline_units AS pipeline_units,
            af.units_delivering_next_12_months AS units_delivering_next_12_months,
            af.active_developers AS active_developers,
            af.avg_completion_pct AS avg_completion_pct,
            af.avg_delivery_confidence AS avg_delivery_confidence,
            af.sales_transaction_count_12m AS sales_transaction_count_12m,
            af.rental_contract_count_12m AS rental_contract_count_12m,
            af.total_sales_volume_12m AS total_sales_volume_12m,
            af.median_sale_price AS median_sale_price,
            af.median_annual_rent AS median_annual_rent,
            af.gross_yield_pct AS gross_yield_pct,
            af.top_developers AS top_developers,
            af.top_master_projects AS top_master_projects,
            ifNull(ds.dda_plot_count, 0) AS dda_plot_count,
            ifNull(ds.dda_total_plot_area_sqm, 0) AS dda_total_plot_area_sqm,
            ifNull(ds.dda_total_gfa_sqm, 0) AS dda_total_gfa_sqm,
            ifNull(ds.dda_dominant_land_uses, []) AS dda_dominant_land_uses
        FROM ch_area_fact af
        LEFT JOIN area_geo ag ON lower(ag.area_name_en) = lower(af.area_name_en)
        LEFT JOIN dda_summary ds ON lower(ds.community_name) = lower(af.area_name_en)
        WHERE af.area_name_en != ''
          AND lower(af.area_name_en) != 'unknown'
        ORDER BY af.pipeline_units DESC, af.sales_transaction_count_12m DESC
        LIMIT 90
    """

    stats_sql = """
        SELECT
            count() AS total_projects,
            (
                SELECT count()
                FROM (
                    SELECT DISTINCT p.project_id
                    FROM ch_projects p
                    INNER JOIN (
                        SELECT DISTINCT project_name_en
                        FROM ch_geo_buildings
                        WHERE lat BETWEEN 20 AND 30
                          AND lng BETWEEN 50 AND 60
                          AND project_name_en != ''
                    ) g ON g.project_name_en = p.project_name_en
                )
            ) AS mapped_projects,
            countIf(completion_status != 'FINISHED') AS active_projects,
            countIf(completion_status = 'FINISHED') AS finished_projects,
            sumIf(no_of_units, completion_status != 'FINISHED') AS pipeline_units,
            sumIf(
                no_of_units,
                pipeline_status = 'delivering_next_12_months' AND completion_status != 'FINISHED'
            )
                AS units_delivering_next_12_months,
            sum(sales_transaction_count_12m) AS sales_transaction_count_12m,
            sum(rental_contract_count_12m) AS rental_contract_count_12m,
            sum(total_sales_volume_12m) AS total_sales_volume_12m,
            (
                SELECT count()
                FROM ch_gis_land_plots FINAL
                WHERE coordinates != ''
            ) AS dda_plot_count,
            (
                SELECT sum(plot_area_sqm)
                FROM ch_gis_land_plots FINAL
                WHERE coordinates != ''
            ) AS dda_total_plot_area_sqm,
            (
                SELECT sum(max_gfa_sqm)
                FROM ch_gis_land_plots FINAL
                WHERE coordinates != ''
            ) AS dda_total_gfa_sqm
        FROM ch_project_fact
    """

    project_rows, area_rows, stats_rows = await asyncio.gather(
        query(project_sql, {"limit": limit}),
        query(area_sql, {}),
        query(stats_sql, {}),
    )

    projects = [
        ProjectRadarProject(
            project_id=row["project_id"],
            project_name=row["project_name_en"],
            area_name=row.get("area_name_en") or "Unknown",
            developer_name=row.get("developer_name") or None,
            master_project_en=row.get("master_project_en") or None,
            latitude=float(row["latitude"]),
            longitude=float(row["longitude"]),
            geo_pin_count=int(row.get("geo_pin_count") or 0),
            completion_status=row.get("completion_status") or "",
            pipeline_status=row.get("pipeline_status") or "",
            project_status=row.get("project_status") or None,
            no_of_units=int(row.get("no_of_units") or 0),
            no_of_buildings=int(row.get("no_of_buildings") or 0),
            percent_completed=_float_or_none(row.get("percent_completed")),
            delivery_confidence=_float_or_none(row.get("estimated_delivery_confidence")) or 0.0,
            sales_transaction_count_12m=int(row.get("sales_transaction_count_12m") or 0),
            rental_contract_count_12m=int(row.get("rental_contract_count_12m") or 0),
            total_sales_volume_12m=_float_or_none(row.get("total_sales_volume_12m")) or 0.0,
            median_sale_price=_float_or_none(row.get("median_sale_price")),
            median_annual_rent=_float_or_none(row.get("median_annual_rent")),
            gross_yield_pct=_float_or_none(row.get("gross_yield_pct")),
            avg_sale_price_sqm_12m=_float_or_none(row.get("avg_sale_price_sqm_12m")),
            avg_rent_price_sqm_12m=_float_or_none(row.get("avg_rent_price_sqm_12m")),
        )
        for row in project_rows
    ]

    areas = [
        ProjectRadarArea(
            area_id=int(row.get("area_id") or 0),
            area_name=row.get("area_name_en") or "Unknown",
            latitude=_float_or_none(row.get("latitude")),
            longitude=_float_or_none(row.get("longitude")),
            mapped_projects=int(row.get("mapped_projects") or 0),
            active_projects=int(row.get("active_projects") or 0),
            completed_projects=int(row.get("completed_projects") or 0),
            overdue_projects=int(row.get("overdue_projects") or 0),
            pipeline_units=int(row.get("pipeline_units") or 0),
            units_delivering_next_12_months=int(
                row.get("units_delivering_next_12_months") or 0
            ),
            active_developers=int(row.get("active_developers") or 0),
            avg_completion_pct=_float_or_none(row.get("avg_completion_pct")) or 0.0,
            avg_delivery_confidence=_float_or_none(row.get("avg_delivery_confidence")) or 0.0,
            sales_transaction_count_12m=int(row.get("sales_transaction_count_12m") or 0),
            rental_contract_count_12m=int(row.get("rental_contract_count_12m") or 0),
            total_sales_volume_12m=_float_or_none(row.get("total_sales_volume_12m")) or 0.0,
            median_sale_price=_float_or_none(row.get("median_sale_price")),
            median_annual_rent=_float_or_none(row.get("median_annual_rent")),
            gross_yield_pct=_float_or_none(row.get("gross_yield_pct")),
            top_developers=list(row.get("top_developers") or [])[:5],
            top_master_projects=list(row.get("top_master_projects") or [])[:5],
            dda_plot_count=int(row.get("dda_plot_count") or 0),
            dda_total_plot_area_sqm=_float_or_none(row.get("dda_total_plot_area_sqm")) or 0.0,
            dda_total_gfa_sqm=_float_or_none(row.get("dda_total_gfa_sqm")) or 0.0,
            dda_dominant_land_uses=_land_use_labels(row.get("dda_dominant_land_uses"), limit=5),
        )
        for row in area_rows
    ]
    unique_areas: list[ProjectRadarArea] = []
    seen_area_names: set[str] = set()
    for area in areas:
        area_key = area.area_name.strip().lower()
        if area_key in seen_area_names:
            continue
        seen_area_names.add(area_key)
        unique_areas.append(area)
    areas = unique_areas

    stats_row = stats_rows[0] if stats_rows else {}
    stats = ProjectRadarStats(
        total_projects=int(stats_row.get("total_projects") or 0),
        mapped_projects=int(stats_row.get("mapped_projects") or 0),
        active_projects=int(stats_row.get("active_projects") or 0),
        finished_projects=int(stats_row.get("finished_projects") or 0),
        pipeline_units=int(stats_row.get("pipeline_units") or 0),
        units_delivering_next_12_months=int(
            stats_row.get("units_delivering_next_12_months") or 0
        ),
        sales_transaction_count_12m=int(stats_row.get("sales_transaction_count_12m") or 0),
        rental_contract_count_12m=int(stats_row.get("rental_contract_count_12m") or 0),
        total_sales_volume_12m=_float_or_none(stats_row.get("total_sales_volume_12m")) or 0.0,
        dda_plot_count=int(stats_row.get("dda_plot_count") or 0),
        dda_total_plot_area_sqm=_float_or_none(stats_row.get("dda_total_plot_area_sqm")) or 0.0,
        dda_total_gfa_sqm=_float_or_none(stats_row.get("dda_total_gfa_sqm")) or 0.0,
    )

    return ProjectRadarResponse(
        stats=stats,
        projects=projects,
        areas=areas,
        source_notes=[
            "Project points are derived from geocoded building pins when available.",
            "Area bubbles combine ch_area_fact metrics with DDA community planning summaries.",
            "DDA outlines load at overview zoom; parcel polygons load only for the zoomed viewport.",
        ],
    )


async def get_building_details(property_id: int) -> Optional[BuildingDetailResponse]:
    """Get building metadata and unit composition by bedroom type."""
    building_sql = """
        SELECT
            property_id,
            building_number,
            floors,
            project_id,
            project_name_en,
            area_name_en
        FROM ch_buildings
        WHERE property_id = {property_id:Int32}
        LIMIT 1
    """
    building_result = await query(building_sql, {"property_id": property_id})
    if not building_result:
        return None

    b = building_result[0]

    units_sql = """
        SELECT
            rooms_en,
            count() AS count,
            round(avg(actual_area), 2) AS avg_area_sqm
        FROM ch_units
        WHERE parent_property_id = {property_id:Int32}
          AND rooms_en != ''
        GROUP BY rooms_en
        ORDER BY count DESC
    """
    units_result = await query(units_sql, {"property_id": property_id})

    total_units = sum(row["count"] for row in units_result)
    unit_composition = [
        BuildingUnitType(
            rooms_en=row["rooms_en"],
            count=row["count"],
            percentage=round((row["count"] / total_units) * 100, 1) if total_units else 0,
            avg_area_sqm=float(row["avg_area_sqm"]) if row["avg_area_sqm"] else None,
        )
        for row in units_result
    ]
    unit_composition.sort(key=lambda row: _room_sort_key(row.rooms_en))

    return BuildingDetailResponse(
        property_id=b["property_id"],
        building_number=b.get("building_number") or None,
        floors=b.get("floors") or None,
        project_id=b["project_id"],
        project_name=b.get("project_name_en") or f"Project {b['project_id']}",
        area_name=b.get("area_name_en") or "Unknown",
        total_units=total_units,
        unit_composition=unit_composition,
    )


def _dubai_local_tm_to_lng_lat(easting: float, northing: float) -> list[float]:
    """Convert Dubai Local Transverse Mercator coordinates to WGS84 lng/lat."""
    semi_major_axis = 6378137.0
    flattening = 1 / 298.257223563
    scale_factor = 1.0
    eccentricity_sq = flattening * (2 - flattening)
    second_eccentricity_sq = eccentricity_sq / (1 - eccentricity_sq)

    x = easting - 500000.0
    y = northing
    central_meridian = math.radians(55.3333333333333)

    meridional_arc = y / scale_factor
    mu = meridional_arc / (
        semi_major_axis
        * (
            1
            - eccentricity_sq / 4
            - 3 * eccentricity_sq**2 / 64
            - 5 * eccentricity_sq**3 / 256
        )
    )

    e1 = (1 - math.sqrt(1 - eccentricity_sq)) / (1 + math.sqrt(1 - eccentricity_sq))
    footprint_lat = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    sin_fp = math.sin(footprint_lat)
    cos_fp = math.cos(footprint_lat)
    tan_fp = math.tan(footprint_lat)

    c1 = second_eccentricity_sq * cos_fp**2
    t1 = tan_fp**2
    n1 = semi_major_axis / math.sqrt(1 - eccentricity_sq * sin_fp**2)
    r1 = (
        semi_major_axis
        * (1 - eccentricity_sq)
        / (1 - eccentricity_sq * sin_fp**2) ** 1.5
    )
    d = x / (n1 * scale_factor)

    lat = footprint_lat - (n1 * tan_fp / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * second_eccentricity_sq) * d**4 / 24
        + (
            61
            + 90 * t1
            + 298 * c1
            + 45 * t1**2
            - 252 * second_eccentricity_sq
            - 3 * c1**2
        )
        * d**6
        / 720
    )
    lon = central_meridian + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (
            5
            - 2 * c1
            + 28 * t1
            - 3 * c1**2
            + 8 * second_eccentricity_sq
            + 24 * t1**2
        )
        * d**5
        / 120
    ) / cos_fp

    return [math.degrees(lon), math.degrees(lat)]


def _normalize_plot_coordinate(pair: Any) -> list[float] | None:
    if not isinstance(pair, list) or len(pair) != 2:
        return None
    try:
        x = float(pair[0])
        y = float(pair[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or not math.isfinite(y):
        return None

    if -180 <= x <= 180 and -90 <= y <= 90:
        return [x, y]
    if 100000 <= x <= 900000 and 0 <= y <= 10000000:
        return _dubai_local_tm_to_lng_lat(x, y)
    return None


def _parse_plot_coordinates(raw: str) -> list[list[float]]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        coords = [
            coordinate
            for p in parsed
            if (coordinate := _normalize_plot_coordinate(p)) is not None
        ]
        if len(coords) >= 3 and coords[0] != coords[-1]:
            coords.append(coords[0])
        return coords
    except Exception:
        return []


def _coordinate_bounds(coordinates: list[list[float]]) -> tuple[float, float, float, float]:
    lngs = [point[0] for point in coordinates]
    lats = [point[1] for point in coordinates]
    return min(lngs), min(lats), max(lngs), max(lats)


def _bounds_intersects(
    plot_bounds: tuple[float, float, float, float],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
) -> bool:
    plot_west, plot_south, plot_east, plot_north = plot_bounds
    return plot_west <= east and plot_east >= west and plot_south <= north and plot_north >= south


async def _get_dda_plot_geometries() -> list[dict[str, Any]]:
    global _dda_geometry_cache

    now = time.monotonic()
    if _dda_geometry_cache and now - _dda_geometry_cache[0] < DDA_GEOMETRY_CACHE_TTL_SECONDS:
        return _dda_geometry_cache[1]

    sql = """
    SELECT
        plot_number,
        project_name,
        community_name,
        plot_area_sqm,
        max_gfa_sqm,
        max_height,
        max_coverage,
        land_use,
        gfa_type,
        is_verified,
        coordinates
    FROM ch_gis_land_plots FINAL
    WHERE coordinates != ''
    LIMIT 100000
    """
    rows = await query(sql, {})
    geometries: list[dict[str, Any]] = []
    for row in rows:
        coordinates = _parse_plot_coordinates(row.get("coordinates", ""))
        if len(coordinates) < 3:
            continue
        geometries.append(
            {
                "plot_number": row.get("plot_number") or "",
                "project_name": row.get("project_name") or "",
                "community_name": row.get("community_name") or "",
                "plot_area_sqm": _float_or_none(row.get("plot_area_sqm")) or 0.0,
                "max_gfa_sqm": _float_or_none(row.get("max_gfa_sqm")),
                "max_height": row.get("max_height") or None,
                "max_coverage": row.get("max_coverage") or None,
                "land_use": row.get("land_use") or None,
                "gfa_type": row.get("gfa_type") or None,
                "is_verified": bool(row.get("is_verified") or False),
                "coordinates": coordinates,
                "bounds": _coordinate_bounds(coordinates),
                "land_use_summary": _land_use_labels(row.get("land_use"), limit=4),
            }
        )

    _dda_geometry_cache = (now, geometries)
    return geometries


def _convex_hull(points: list[list[float]]) -> list[list[float]]:
    unique_points = sorted({(round(point[0], 8), round(point[1], 8)) for point in points})
    if len(unique_points) < 3:
        return []

    def cross(
        origin: tuple[float, float],
        point_a: tuple[float, float],
        point_b: tuple[float, float],
    ) -> float:
        return (point_a[0] - origin[0]) * (point_b[1] - origin[1]) - (
            point_a[1] - origin[1]
        ) * (point_b[0] - origin[0])

    lower: list[tuple[float, float]] = []
    for point in unique_points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(unique_points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    hull = [[lng, lat] for lng, lat in lower[:-1] + upper[:-1]]
    if len(hull) >= 3:
        hull.append(hull[0])
    return hull


async def get_dda_outlines_for_bounds(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    zoom: float,
    limit: int = 160,
) -> list[DDAOutlineFeature]:
    """Return coarse DDA outlines for low-zoom planning context."""
    rows = await _get_dda_plot_geometries()
    group_by_project = zoom >= 12
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        coords = row["coordinates"]
        if not _bounds_intersects(
            row["bounds"],
            west=west,
            south=south,
            east=east,
            north=north,
        ):
            continue

        project_name = str(row.get("project_name") or "").strip()
        community_name = str(row.get("community_name") or "").strip()
        name = project_name if group_by_project and project_name else community_name
        if not name:
            continue

        group = groups.setdefault(
            name,
            {
                "name": name,
                "kind": "project" if group_by_project and project_name else "community",
                "points": [],
                "plot_count": 0,
                "total_plot_area_sqm": 0.0,
                "total_gfa_sqm": 0.0,
                "land_uses": [],
            },
        )
        group["points"].extend(coords[:-1] if coords[0] == coords[-1] else coords)
        group["plot_count"] += 1
        group["total_plot_area_sqm"] += row["plot_area_sqm"]
        group["total_gfa_sqm"] += row["max_gfa_sqm"] or 0.0
        group["land_uses"].extend(row["land_use_summary"][:2])

    min_plot_count = 8 if zoom < 12 else 3
    outlines: list[DDAOutlineFeature] = []
    for group in sorted(
        groups.values(),
        key=lambda item: (item["plot_count"], item["total_plot_area_sqm"]),
        reverse=True,
    ):
        if group["plot_count"] < min_plot_count:
            continue
        hull = _convex_hull(group["points"])
        if len(hull) < 4:
            continue
        land_uses = list(dict.fromkeys(group["land_uses"]))[:4]
        outlines.append(
            DDAOutlineFeature(
                name=group["name"],
                kind=group["kind"],
                plot_count=group["plot_count"],
                total_plot_area_sqm=round(group["total_plot_area_sqm"], 2),
                total_gfa_sqm=round(group["total_gfa_sqm"], 2),
                coordinates=hull,
                land_use_summary=land_uses,
            )
        )
        if len(outlines) >= limit:
            break
    return outlines


async def get_project_market_snapshot(project_id: int) -> Optional[ProjectMarketSnapshotResponse]:
    result = await query(
        """
        SELECT
            project_id,
            project_name_en,
            area_name_en,
            developer_name,
            master_project_en,
            completion_status,
            pipeline_status,
            estimated_delivery_confidence,
            sales_transaction_count_12m,
            rental_contract_count_12m,
            total_sales_volume_12m,
            median_sale_price,
            median_annual_rent,
            gross_yield_pct,
            avg_sale_price_sqm_12m,
            avg_rent_price_sqm_12m
        FROM ch_project_fact
        WHERE project_id = {project_id:Int32}
        LIMIT 1
        """,
        {"project_id": project_id},
    )
    if not result:
        return None
    row = result[0]
    return ProjectMarketSnapshotResponse(
        project_id=row["project_id"],
        project_name=row.get("project_name_en") or f"Project {row['project_id']}",
        area_name=row.get("area_name_en") or "Unknown",
        developer_name=row.get("developer_name") or None,
        master_project_en=row.get("master_project_en") or None,
        completion_status=row.get("completion_status") or "planned",
        pipeline_status=row.get("pipeline_status") or "unscheduled",
        estimated_delivery_confidence=float(row.get("estimated_delivery_confidence") or 0),
        sales_transaction_count_12m=row.get("sales_transaction_count_12m", 0),
        rental_contract_count_12m=row.get("rental_contract_count_12m", 0),
        total_sales_volume_12m=float(row.get("total_sales_volume_12m") or 0),
        median_sale_price=row.get("median_sale_price"),
        median_annual_rent=row.get("median_annual_rent"),
        gross_yield_pct=row.get("gross_yield_pct"),
        avg_sale_price_sqm_12m=row.get("avg_sale_price_sqm_12m"),
        avg_rent_price_sqm_12m=row.get("avg_rent_price_sqm_12m"),
    )


def _plot_intersects_bounds(
    coordinates: list[list[float]],
    *,
    west: float,
    south: float,
    east: float,
    north: float,
) -> bool:
    if not coordinates:
        return False
    lngs = [point[0] for point in coordinates]
    lats = [point[1] for point in coordinates]
    return min(lngs) <= east and max(lngs) >= west and min(lats) <= north and max(lats) >= south


async def get_dda_plots_for_area(
    area: str | None = None,
    limit: int = 300,
    west: float | None = None,
    south: float | None = None,
    east: float | None = None,
    north: float | None = None,
) -> list[DDAPlotFeature]:
    """Return DDA GIS plot polygons for a community or current map bounds."""
    has_bounds = all(value is not None for value in (west, south, east, north))
    area_query = area.strip().lower() if area else ""
    rows = await _get_dda_plot_geometries()
    results: list[DDAPlotFeature] = []
    for row in rows:
        if area_query and area_query not in " ".join(
            [row["community_name"], row["project_name"]]
        ).lower():
            continue
        if has_bounds and not _bounds_intersects(
            row["bounds"],
            west=west or 0,
            south=south or 0,
            east=east or 0,
            north=north or 0,
        ):
            continue
        results.append(
            DDAPlotFeature(
                plot_number=row["plot_number"],
                project_name=row["project_name"],
                community_name=row["community_name"],
                plot_area_sqm=row["plot_area_sqm"],
                coordinates=row["coordinates"],
                land_use_summary=row["land_use_summary"],
                max_gfa_sqm=row["max_gfa_sqm"],
                max_height=row["max_height"],
                max_coverage=row["max_coverage"],
                land_use=row["land_use"],
                gfa_type=row["gfa_type"],
                is_verified=row["is_verified"],
            )
        )
        if len(results) >= limit:
            break
    return results
