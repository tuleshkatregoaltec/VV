from pydantic import BaseModel, ConfigDict, computed_field, Field
from typing import Optional, Any, List, TYPE_CHECKING

if TYPE_CHECKING:
    pass


class DeveloperResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    developer_id: int
    developer_name_en: Optional[str] = None
    phone: Optional[str] = None
    webpage: Optional[str] = None
    total: int = 0
    active: int = 0
    completed: int = 0
    cancelled: int = 0


class DeveloperListResponse(BaseModel):
    """Paginated list of developers."""

    developers: List[DeveloperResponse]
    total: int
    limit: int
    offset: int


class DeveloperCountResponse(BaseModel):
    """Developer count response."""

    total: int


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    project_name: Optional[str] = None
    project_status: Optional[str] = None
    percent_completed: Optional[int] = None
    project_start_date: Optional[Any] = None
    project_end_date: Optional[Any] = None
    completion_date: Optional[Any] = None
    cancellation_date: Optional[Any] = None
    project_description_en: Optional[str] = None
    no_of_buildings: Optional[int] = None
    no_of_units: Optional[int] = None

    # Exclude from serialization - only used to compute area_name
    area: Optional[Any] = Field(default=None, exclude=True)

    @computed_field
    @property
    def area_name(self) -> Optional[str]:
        """Extract name from the area relationship."""
        if self.area and hasattr(self.area, "name_en"):
            return self.area.name_en
        return None
