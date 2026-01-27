"""Project and building services - redesigned for ClickHouse from first principles."""

from typing import List, Optional
from app.project.models import (
    ProjectSearchResult,
    ProjectDetailResponse,
    BuildingInfo,
    UnitComposition,
)
from app.clickhouse.client import query
import logging

logger = logging.getLogger(__name__)


async def list_all_projects() -> List[ProjectSearchResult]:
    """
    Get all projects with minimal data for client-side search.

    Returns ~1500 projects for frontend filtering.
    Uses default Dubai center coordinates (will be updated when user selects project).
    """
    sql = """
        SELECT
            project_id,
            project_name,
            area_name_en,
            developer_name
        FROM ch_projects
        ORDER BY project_name
        LIMIT 2000
    """

    result = await query(sql, {})

    return [
        ProjectSearchResult(
            project_id=p["project_id"],
            project_name=p["project_name"] or f"Project {p['project_id']}",
            area_name=p.get("area_name_en", "Unknown"),
            developer_name=p.get("developer_name"),
            latitude=25.2048,  # Default Dubai center
            longitude=55.2708,
        )
        for p in result
    ]


async def get_project_details(project_id: int) -> Optional[ProjectDetailResponse]:
    """
    Get full project details including buildings and unit composition.

    Optimized using ORDER BY project_id for fast lookup.
    """
    # Fetch project details
    project_sql = """
        SELECT
            project_id,
            project_number,
            project_name,
            developer_id,
            developer_name,
            master_developer_id,
            master_developer_name,
            area_id,
            area_name_en,
            no_of_buildings,
            no_of_units,
            no_of_villas,
            no_of_lands,
            project_start_date,
            project_end_date,
            completion_date,
            percent_completed,
            project_status,
            escrow_agent_name,
            zoning_authority_en
        FROM ch_projects
        WHERE project_id = {project_id:Int32}
        LIMIT 1
    """

    project_result = await query(project_sql, {"project_id": project_id})

    if not project_result:
        return None

    project = project_result[0]

    # Get buildings for this project (if project_number exists)
    buildings: List[BuildingInfo] = []
    if project.get("project_number"):
        buildings_sql = """
            SELECT
                property_id,
                building_number,
                floors,
                project_number,
                project_name_en
            FROM ch_buildings
            WHERE project_number = {project_number:String}
            ORDER BY building_number
            LIMIT 100
        """

        buildings_result = await query(
            buildings_sql,
            {"project_number": project["project_number"]},
        )

        logger.info(f"Found {len(buildings_result)} buildings for project {project_id}")

        # Build building info list
        for building in buildings_result:
            building_name = (
                building.get("building_number") or f"Building {building['property_id']}"
            )
            buildings.append(
                BuildingInfo(
                    property_id=building["property_id"],
                    building_number=building.get("building_number"),
                    building_name=building_name,
                    floors=building.get("floors"),
                    latitude=25.2048,  # Default - will be updated with actual coords later
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
            GROUP BY property_sub_type_en
            ORDER BY count DESC
        """

        composition_result = await query(
            composition_sql,
            {"project_id": project_id},
        )

        # Calculate total for percentages
        total_units = sum(row["count"] for row in composition_result)

        if total_units > 0:
            for row in composition_result:
                unit_composition.append(
                    UnitComposition(
                        property_sub_type=row["property_sub_type_en"] or "Unknown",
                        count=row["count"],
                        percentage=round((row["count"] / total_units) * 100, 2),
                        avg_area_sqm=float(row["avg_area_sqm"])
                        if row["avg_area_sqm"]
                        else None,
                    )
                )

    # Build response
    return ProjectDetailResponse(
        project_id=project["project_id"],
        project_name=project["project_name"] or f"Project {project['project_id']}",
        project_number=project.get("project_number"),
        area_id=project.get("area_id"),
        area_name=project.get("area_name_en", "Unknown"),
        latitude=25.2048,  # Default Dubai center - will be geocoded later
        longitude=55.2708,
        area_polygon=None,  # No polygon data in current schema
        developer_id=project.get("developer_id"),
        developer_name=project.get("developer_name"),
        master_developer_id=project.get("master_developer_id"),
        master_developer_name=project.get("master_developer_name"),
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
