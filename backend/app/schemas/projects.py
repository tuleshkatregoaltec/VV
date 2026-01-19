from pydantic import BaseModel
from typing import Optional, List
from datetime import date


class ProjectSearchResult(BaseModel):
    """Minimal project info for search dropdown"""
    project_id: int
    project_name: str
    area_name: str
    developer_name: Optional[str]


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
