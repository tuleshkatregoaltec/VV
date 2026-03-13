"""Project and building services - redesigned for ClickHouse from first principles."""

import asyncio
import logging
import re
from typing import List, Optional

from app.clickhouse.client import query
from app.project.models import (
    BuildingDetailResponse,
    BuildingInfo,
    BuildingUnitType,
    GeoPin,
    GeoPolygon,
    MasterProjectResponse,
    MasterProjectSummary,
    ProjectDetailResponse,
    ProjectSearchResult,
    ProjectUnitComposition,
)

logger = logging.getLogger(__name__)


def _room_sort_key(rooms: str) -> tuple:
    normalized = rooms.strip()
    if normalized.lower() == "studio":
        return (0, 0, normalized)
    match = re.match(r"^(\d+)", normalized)
    if match:
        return (1, int(match.group(1)), normalized)
    return (2, 0, normalized.lower())


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
