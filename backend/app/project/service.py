"""Project and building services - redesigned for ClickHouse from first principles."""

from typing import List, Optional
from app.project.models import (
    ProjectSearchResult,
    ProjectDetailResponse,
    GeoPolygon,
    BuildingInfo,
    UnitComposition,
    BuildingDetailResponse,
    BuildingUnitType,
)
from app.clickhouse.client import query
import logging

logger = logging.getLogger(__name__)


async def list_all_projects() -> List[ProjectSearchResult]:
    """Get all projects with minimal data for client-side search."""
    sql = """
        SELECT
            p.project_id AS project_id,
            p.project_name_en,
            p.area_name_en,
            p.master_project_en,
            COALESCE(NULLIF(d.developer_name_en, ''), p.developer_name) AS developer_name,
            COALESCE(g.centroid_lat, 25.2048) AS latitude,
            COALESCE(g.centroid_lng, 55.2708) AS longitude
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
            COALESCE(g.centroid_lat, 25.2048) AS latitude,
            COALESCE(g.centroid_lng, 55.2708) AS longitude,
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

    # Get buildings for this project
    buildings: List[BuildingInfo] = []
    buildings_sql = """
        SELECT
            property_id,
            building_number,
            floors
        FROM ch_buildings
        WHERE project_id = {project_id:Int32}
        ORDER BY building_number
        LIMIT 100
    """

    buildings_result = await query(buildings_sql, {"project_id": project_id})
    logger.info(f"Found {len(buildings_result)} buildings for project {project_id}")

    for building in buildings_result:
        building_name = building.get("building_number") or f"Building {building['property_id']}"
        buildings.append(
            BuildingInfo(
                property_id=building["property_id"],
                building_number=building.get("building_number"),
                building_name=building_name,
                floors=building.get("floors") or None,
                latitude=25.2048,
                longitude=55.2708,
            )
        )

    # Get unit composition from ch_units (grouped by property_sub_type_en)
    unit_composition: List[UnitComposition] = []
    if project.get("project_id"):
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

        composition_result = await query(composition_sql, {"project_id": project_id})

        total_units = sum(row["count"] for row in composition_result)

        if total_units > 0:
            for row in composition_result:
                unit_composition.append(
                    UnitComposition(
                        property_sub_type=row["property_sub_type_en"],
                        count=row["count"],
                        percentage=round((row["count"] / total_units) * 100, 2),
                        avg_area_sqm=float(row["avg_area_sqm"]) if row["avg_area_sqm"] else None,
                    )
                )

    raw_polygon = project.get("area_polygon") or []
    area_polygon = GeoPolygon(coordinates=raw_polygon) if raw_polygon else None

    return ProjectDetailResponse(
        project_id=project["project_id"],
        project_name=project["project_name_en"] or f"Project {project['project_id']}",
        project_number=project.get("project_number"),
        master_project_en=project.get("master_project_en") or None,
        area_id=project.get("area_id"),
        area_name=project.get("area_name_en", "Unknown"),
        latitude=project["latitude"],
        longitude=project["longitude"],
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
