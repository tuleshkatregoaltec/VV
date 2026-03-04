from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class GeoPolygon(BaseModel):
    """Geographic polygon (area boundaries)"""

    coordinates: List[List[float]]  # List of [lng, lat] pairs


class BuildingInfo(BaseModel):
    """Building with property_id for drilldown"""

    property_id: int
    building_number: Optional[str]
    building_name: Optional[str]
    floors: Optional[int]


class GeoPin(BaseModel):
    """Geocoded pin for map display"""

    building_name: str
    project_name: str
    latitude: float
    longitude: float
    property_id: Optional[int] = None


class MasterProjectSummary(BaseModel):
    """Summary of a sub-project within a master"""

    project_id: int
    project_name: str
    project_status: Optional[str]
    percent_completed: Optional[float]
    no_of_buildings: Optional[int]
    no_of_units: Optional[int]


class MasterProjectResponse(BaseModel):
    """Aggregated data for a master project"""

    master_name: str
    area_name: str
    developer_name: Optional[str]
    total_projects: int
    total_buildings: int
    total_units: int
    projects: List[MasterProjectSummary]
    geo_pins: List[GeoPin]
    unit_composition: List["UnitComposition"]


class ProjectSearchResult(BaseModel):
    """Minimal project info for search dropdown"""

    project_id: int
    project_name: str
    area_name: str
    developer_name: Optional[str]
    master_project_en: Optional[str]
    latitude: float
    longitude: float


class UnitComposition(BaseModel):
    """Unit type breakdown"""

    property_sub_type: str  # "Studio", "1 B/R", "2 B/R", "3 B/R", "Penthouse"
    count: int
    percentage: float  # 0-100
    avg_area_sqm: Optional[float]


class BuildingUnitType(BaseModel):
    """Bedroom/type breakdown for a specific building"""

    rooms_en: str  # "Studio", "1 B/R", "2 B/R", etc.
    count: int
    percentage: float
    avg_area_sqm: Optional[float]


class BuildingDetailResponse(BaseModel):
    """Building-level details with unit composition"""

    property_id: int
    building_number: Optional[str]
    floors: Optional[int]
    project_id: int
    project_name: str
    area_name: str
    total_units: int
    unit_composition: List[BuildingUnitType]


class ProjectDetailResponse(BaseModel):
    """Full project details for overlay"""

    # Basic info
    project_id: int
    project_name: str
    project_number: Optional[str]
    master_project_en: Optional[str]

    # Location
    area_id: Optional[int]
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
    percent_completed: Optional[float]
    project_status: Optional[str]

    # Derived data
    unit_composition: List[UnitComposition]
    buildings: List[BuildingInfo] = []
    geo_pins: List[GeoPin] = []
