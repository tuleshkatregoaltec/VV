from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.core.decorators import cached_endpoint
from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.schemas.supply import (
    UpcomingProjectResponse,
    UpcomingProjectsResponse,
)
from backend.app.services.supply_service import get_upcoming_projects

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supply"],
    dependencies=[Depends(require_auth)],
)


@router.get("/upcoming-projects", response_model=UpcomingProjectsResponse)
@cached_endpoint(prefix="upcoming_projects", expire=3600)
async def list_upcoming_projects(
    db: AsyncSession = Depends(get_db_session),
):
    """Get all upcoming/active projects for catalogue view."""
    projects = await get_upcoming_projects(db)

    # Build response
    result = []
    for project in projects:
        project_data = {
            "project_id": project.project_id,
            "project_name": project.project_name,
            "developer_name": project.developer.developer_name_en if project.developer else "Unknown",
            "developer_id": project.developer_id,
            "area_name": project.area.name_en if project.area else "Unknown",
            "project_start_date": project.project_start_date,
            "project_end_date": project.project_end_date,
            "percent_completed": project.percent_completed or 0,
            "no_of_buildings": project.no_of_buildings,
            "no_of_units": project.no_of_units,
        }
        result.append(UpcomingProjectResponse.model_validate(project_data))

    return UpcomingProjectsResponse(projects=result, total=len(result))
