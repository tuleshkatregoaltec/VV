from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import List, Literal

from backend.app.db.session import get_db_session
from backend.app.routers.dependencies import require_auth
from backend.app.core.decorators import cached_endpoint
from backend.app.schemas.supply import (
    DeveloperResponse,
    DeveloperListResponse,
    DeveloperCountResponse,
    ProjectResponse,
)

from backend.app.services.supply_service import (
    get_all_developers,
    get_developer_count,
    get_developer_stats_bulk,
    get_projects_by_developer,
    get_project_by_id,
)

router = APIRouter(
    prefix="/api/v1/supply",
    tags=["supply"],
    dependencies=[Depends(require_auth)],
)


@router.get("/developers/count", response_model=DeveloperCountResponse)
@cached_endpoint(prefix="developers_count", expire=300)
async def count_developers(
    session: AsyncSession = Depends(get_db_session),
):
    """Get total count of developers."""
    total = await get_developer_count(session)
    return DeveloperCountResponse(total=total)


@router.get("/developers", response_model=DeveloperListResponse)
async def list_developers(
    sort_by: Literal["projects", "transactions", "avg_price"] = Query("projects"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
):
    """Get developers with pagination, sorted by specified criteria.

    Uses bulk stats fetching to avoid N+1 query problem.
    """
    # Fetch total count and paginated developers
    total = await get_developer_count(session)
    developers = await get_all_developers(
        session, sort_by=sort_by, limit=limit, offset=offset
    )

    # Extract developer IDs and fetch all stats in one query
    dev_ids = [dev.developer_id for dev in developers]
    stats_map = await get_developer_stats_bulk(session, dev_ids)

    # Merge developer data with stats (CPU-bound, fast)
    result = []
    for dev in developers:
        stats = stats_map.get(
            dev.developer_id, {"total": 0, "active": 0, "completed": 0, "cancelled": 0}
        )
        dev_data = {
            "developer_id": dev.developer_id,
            "developer_name_en": dev.developer_name_en,
            "phone": dev.phone,
            "webpage": dev.webpage,
            **stats,
        }
        result.append(DeveloperResponse.model_validate(dev_data))

    return DeveloperListResponse(
        developers=result, total=total, limit=limit, offset=offset
    )


@router.get("/developers/{developer_id}/projects", response_model=List[ProjectResponse])
@cached_endpoint(prefix="developer_projects", expire=1800)
async def list_developer_projects(
    developer_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    """Get projects for a developer, active first."""
    projects = await get_projects_by_developer(session, developer_id)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
@cached_endpoint(prefix="project", expire=3600)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_db_session),
):
    project = await get_project_by_id(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)
