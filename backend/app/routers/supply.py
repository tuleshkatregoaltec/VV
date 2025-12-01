from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Literal

from backend.app.db.session import get_db_session
from backend.app.services.auth_service import get_current_user
from backend.app.db.models import User
from backend.app.core.decorators import cached_endpoint
from backend.app.schemas.supply import DeveloperResponse, ProjectResponse

from backend.app.services.supply_service import (
    get_all_developers,
    get_developer_by_id,
    get_developer_stats,
    get_projects_by_developer,
    get_project_by_id
)

router = APIRouter(prefix="/supply", tags=["supply"])


@router.get("/developers", response_model=List[DeveloperResponse])
async def list_developers(
    sort_by: Literal['projects', 'transactions', 'avg_price'] = Query('projects', description="Sort developers by"),
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Get all developers sorted by specified criteria."""
    developers = await get_all_developers(session, sort_by=sort_by)
    result = []
    for dev in developers:
        stats = await get_developer_stats(session, dev.developer_id)
        # Merge ORM model with computed stats
        dev_data = {
            "developer_id": dev.developer_id,
            "developer_name": dev.developer_name,
            "phone": dev.phone,
            "webpage": dev.webpage,
            **stats
        }
        result.append(DeveloperResponse.model_validate(dev_data))
    return result


@router.get("/developers/{developer_id}/projects", response_model=List[ProjectResponse])
@cached_endpoint(prefix="developer_projects", expire=1800)
async def list_developer_projects(
    developer_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    """Get projects for a developer, active first."""
    projects = await get_projects_by_developer(session, developer_id)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
@cached_endpoint(prefix="project", expire=3600)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    project = await get_project_by_id(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)
