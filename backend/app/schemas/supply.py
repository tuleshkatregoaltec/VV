from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class UpcomingProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    project_name: str
    developer_name: str
    developer_id: Optional[int] = None
    area_name: str
    project_start_date: Optional[date] = None
    project_end_date: Optional[date] = None
    percent_completed: int = 0
    no_of_buildings: Optional[int] = None
    no_of_units: Optional[int] = None


class UpcomingProjectsResponse(BaseModel):
    projects: List[UpcomingProjectResponse]
    total: int
