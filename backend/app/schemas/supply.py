from pydantic import BaseModel
from typing import Optional, List, ClassVar
from decimal import Decimal
from datetime import date

class DeveloperResponse(BaseModel):

    developer_id: int
    developer_name: Optional[str] = None
    webpage: Optional[str] = None
    phone: Optional[str] = None


class DeveloperListResponse(BaseModel):
    
    developers: List[DeveloperResponse]
    total: int

class ProjectResponse(BaseModel):
    
    project_id: int
    project_name: Optional[str] = None
    
    project_start_date: Optional[date] = None
    project_end_date: Optional[date] = None
    completion_date: Optional[date] = None
    cancellation_date: Optional[date] = None

    project_status: Optional[str] = None
    percent_completed: Optional[int] = None

    area_id: Optional[int] = None

    project_description: Optional[str] = None
    
    no_of_lands: Optional[int] = None
    no_of_buildings: Optional[int] = None
    no_of_villas: Optional[int] = None
    no_of_units: Optional[int] = None


class ProjectListResponse(BaseModel):
    
    projects: List[ProjectResponse]
    total: int