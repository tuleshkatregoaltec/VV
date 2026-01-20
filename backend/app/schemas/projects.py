from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class GeoPoint(BaseModel):
    """Geographic point with latitude and longitude"""

    latitude: float
    longitude: float


class GeoPolygon(BaseModel):
    """Geographic polygon (area boundaries)"""

    coordinates: List[List[float]]  # List of [lng, lat] pairs


class BuildingInfo(BaseModel):
    """Building information with coordinates"""

    property_id: int
    building_number: Optional[str]
    building_name: Optional[str]
    floors: Optional[int]
    latitude: float
    longitude: float


class ProjectSearchResult(BaseModel):
    """Minimal project info for search dropdown"""

    project_id: int
    project_name: str
    area_name: str
    developer_name: Optional[str]
    latitude: float
    longitude: float


class UnitComposition(BaseModel):
    """Unit type breakdown"""

    property_sub_type: str  # "Studio", "1 B/R", "2 B/R", "3 B/R", "Penthouse"
    count: int
    percentage: float  # 0-100
    avg_area_sqm: Optional[float]


class ProjectDetailResponse(BaseModel):
    """Full project details for overlay"""

    # Basic info
    project_id: int
    project_name: str
    project_number: Optional[int]

    # Location
    area_id: int
    area_name: str
    latitude: float
    longitude: float
    area_polygon: Optional[GeoPolygon] = None

    # Developer
    developer_id: Optional[int]
    developer_name: Optional[str]
    master_developer_id: Optional[int]
    master_developer_name: Optional[str]

    # Metrics
    no_of_buildings: Optional[int]
    no_of_units: Optional[int]
    no_of_villas: Optional[int]
    no_of_lands: Optional[int]

    # Timeline
    project_start_date: Optional[date]
    project_end_date: Optional[date]
    completion_date: Optional[date]
    percent_completed: Optional[int]
    project_status: Optional[str]

    # Derived data
    unit_composition: List[UnitComposition]
    buildings: List[BuildingInfo] = []
