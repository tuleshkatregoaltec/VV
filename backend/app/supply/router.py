from fastapi import APIRouter, Depends

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.supply.models import (
    UpcomingProjectResponse,
    UpcomingProjectsResponse,
)
from app.supply.service import get_upcoming_projects_ch

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supply"],
)


@router.get("/upcoming-projects", response_model=UpcomingProjectsResponse)
@cached_endpoint(prefix="upcoming_projects", expire=3600)
async def list_upcoming_projects(
    context: AuthContext = Depends(require_active_subscription),
):
    """Get all upcoming/active projects for catalogue view."""
    projects = await get_upcoming_projects_ch()

    # Build response
    result = []
    for project in projects:
        project_data = {
            "project_id": project.get("project_id"),
            "project_name": project.get("project_name_en")
            or project.get("project_name_ar")
            or "Unknown",
            "developer_name": project.get("developer_name") or "Unknown",
            "developer_id": project.get("developer_id"),
            "area_name": project.get("area_name_en") or "Unknown",
            "project_start_date": project.get("project_start_date"),
            "project_end_date": project.get("project_end_date"),
            "percent_completed": project.get("percent_completed") or 0,
            "no_of_buildings": project.get("no_of_buildings"),
            "no_of_units": project.get("no_of_units"),
        }
        result.append(UpcomingProjectResponse.model_validate(project_data))

    return UpcomingProjectsResponse(projects=result, total=len(result))
