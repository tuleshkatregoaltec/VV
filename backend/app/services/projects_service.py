# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
from typing import List, Optional
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.models.properties import Project, Developer, Unit, Building
from app.db.models.geography import Area
from app.db.models.lookups import PropertySubType
from app.schemas.projects import (
    ProjectSearchResult,
    ProjectDetailResponse,
    UnitComposition,
    GeoPoint,
    GeoPolygon,
    BuildingInfo,
)
from app.services.geocoding_service import search_location, search_location_with_polygon
import logging

logger = logging.getLogger(__name__)

# Simple in-memory cache for geocoding results to avoid repeated API calls
_geocoding_cache: dict[str, Optional[tuple[float, float]]] = {}
_polygon_cache: dict[str, Optional[GeoPolygon]] = {}


async def list_all_projects(db: AsyncSession) -> List[ProjectSearchResult]:
    """
    Get all projects with minimal data for client-side search.
    Returns ~1500 projects (~150-200KB uncompressed).
    NOTE: Does NOT geocode - we only geocode when user selects a project detail
    """
    stmt = (
        select(Project)
        .options(selectinload(Project.developer), selectinload(Project.area))
        .order_by(Project.project_name_en)
    )

    result = await db.exec(stmt)
    projects = result.all()

    return [
        ProjectSearchResult(
            project_id=p.project_id,
            project_name=p.project_name_en
            or p.project_name_ar
            or f"Project {p.project_id}",
            area_name=p.area.name_en if p.area else "Unknown",
            developer_name=p.developer.developer_name_en if p.developer else None,
            latitude=25.2048,  # Default Dubai center - will be updated when user selects
            longitude=55.2708,
        )
        for p in projects
    ]


async def get_project_details(
    db: AsyncSession, project_id: int
) -> Optional[ProjectDetailResponse]:
    """
    Get full project details including unit composition, coordinates, and buildings.
    """
    # Fetch project with relationships
    stmt = (
        select(Project)
        .where(Project.project_id == project_id)
        .options(
            selectinload(Project.developer),
            selectinload(Project.master_developer),
            selectinload(Project.area),
        )
    )

    result = await db.exec(stmt)
    project = result.one_or_none()

    if not project:
        return None

    # Aggregate unit composition
    unit_comp_stmt = (
        select(
            PropertySubType.property_sub_type_en,
            func.count(Unit.property_id).label("count"),
            func.avg(Unit.actual_area).label("avg_area"),
        )
        .join(Unit, Unit.property_sub_type_id == PropertySubType.property_sub_type_id)
        .where(Unit.project_id == project_id)
        .group_by(PropertySubType.property_sub_type_en)
    )

    unit_comp_result = await db.exec(unit_comp_stmt)
    unit_comp_rows = unit_comp_result.all()

    # Calculate total for percentages
    total_units = sum(row.count for row in unit_comp_rows)

    unit_composition = [
        UnitComposition(
            property_sub_type=row.property_sub_type_en,
            count=row.count,
            percentage=round((row.count / total_units * 100), 1)
            if total_units > 0
            else 0,
            avg_area_sqm=float(row.avg_area) if row.avg_area else None,
        )
        for row in unit_comp_rows
    ]

    # Get project and area coordinates
    project_name = project.project_name_en or project.project_name_ar or f"Project {project_id}"
    area_name = project.area.name_en if project.area else "Unknown"
    
    logger.info(f"Geocoding project: {project_name}, area: {area_name}")
    
    # Check caches
    project_cache_key = f"project_{project_name}"
    area_cache_key = f"area_{area_name}"
    
    # Get project coordinates
    if project_cache_key in _geocoding_cache:
        project_cached = _geocoding_cache[project_cache_key]
        if project_cached:
            latitude, longitude = project_cached
            logger.info(f"Using cached project coordinates")
        else:
            latitude, longitude = 25.2048, 55.2708
    else:
        project_geo = await search_location(f"{project_name}, Dubai")
        if project_geo:
            logger.info(f"Found project coordinates: {project_geo.latitude}, {project_geo.longitude}")
            latitude, longitude = project_geo.latitude, project_geo.longitude
            _geocoding_cache[project_cache_key] = (latitude, longitude)
        else:
            logger.warning(f"Could not find coordinates for project {project_name}")
            latitude, longitude = 25.2048, 55.2708
            _geocoding_cache[project_cache_key] = None
    
    # Get area polygon
    area_polygon = None
    if area_cache_key in _polygon_cache:
        area_polygon = _polygon_cache[area_cache_key]
        if area_polygon:
            logger.info(f"Using cached area polygon with {len(area_polygon.coordinates)} points")
    else:
        area_geo = await search_location_with_polygon(f"{area_name}, Dubai")
        if area_geo:
            area_polygon = area_geo[1]
            logger.info(f"Found area polygon with {len(area_polygon.coordinates) if area_polygon else 0} points")
            _polygon_cache[area_cache_key] = area_polygon
        else:
            logger.warning(f"Could not find area polygon for {area_name}")
            _polygon_cache[area_cache_key] = None

    # Get buildings in this project
    buildings_stmt = (
        select(Building)
        .where(Building.project_id == project_id)
        .options(selectinload(Building.area))
    )
    
    buildings_result = await db.exec(buildings_stmt)
    buildings_data = buildings_result.all()
    
    logger.info(f"Found {len(buildings_data)} buildings for project {project_id}")
    
    # Geocode buildings with caching to avoid spamming Nominatim
    buildings: List[BuildingInfo] = []
    for building in buildings_data:
        building_name = building.building_number or f"Building {building.property_id}"
        cache_key = f"{building_name}_{area_name}"
        
        # Check cache first
        if cache_key in _geocoding_cache:
            cached_coords = _geocoding_cache[cache_key]
            if cached_coords:
                lat, lon = cached_coords
                logger.debug(f"Using cached coordinates for {building_name}")
                buildings.append(
                    BuildingInfo(
                        property_id=building.property_id,
                        building_number=building.building_number,
                        building_name=building_name,
                        floors=building.floors,
                        latitude=lat,
                        longitude=lon,
                    )
                )
            continue
        
        # Only geocode if not in cache
        building_geo = await search_location(f"{building_name}, {area_name}, Dubai")
        
        if building_geo:
            logger.debug(f"Found building {building_name}: {building_geo.latitude}, {building_geo.longitude}")
            _geocoding_cache[cache_key] = (building_geo.latitude, building_geo.longitude)
            buildings.append(
                BuildingInfo(
                    property_id=building.property_id,
                    building_number=building.building_number,
                    building_name=building_name,
                    floors=building.floors,
                    latitude=building_geo.latitude,
                    longitude=building_geo.longitude,
                )
            )
        else:
            logger.debug(f"Could not find coordinates for building {building_name}")
            _geocoding_cache[cache_key] = None

    # Build response
    return ProjectDetailResponse(
        project_id=project.project_id,
        project_name=project_name,
        project_number=project.project_number,
        area_id=project.area_id,
        area_name=area_name,
        latitude=latitude,
        longitude=longitude,
        area_polygon=area_polygon,
        developer_id=project.developer_id,
        developer_name=project.developer.developer_name_en if project.developer else None,
        master_developer_id=project.master_developer_id,
        master_developer_name=project.master_developer.developer_name_en
        if project.master_developer
        else None,
        no_of_buildings=project.no_of_buildings,
        no_of_units=project.no_of_units,
        no_of_villas=project.no_of_villas,
        no_of_lands=project.no_of_lands,
        project_start_date=project.project_start_date,
        project_end_date=project.project_end_date,
        completion_date=project.completion_date,
        percent_completed=project.percent_completed,
        project_status=project.project_status,
        unit_composition=unit_composition,
        buildings=buildings,
    )
