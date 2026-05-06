from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.postgres import get_db_session
from app.supply.models import (
    SupplyCatalogueProjectDetailResponse,
    SupplyCatalogueProjectsResponse,
    UpcomingProjectResponse,
    UpcomingProjectsResponse,
)
from app.supply.service import (
    get_supply_catalogue_asset_file,
    get_supply_catalogue_project,
    get_upcoming_projects_ch,
    list_supply_catalogue_projects,
    supply_catalogue_download_filename,
)

router = APIRouter(prefix="/api/v1/supply", tags=["supply"])


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


@router.get("/catalogue/projects", response_model=SupplyCatalogueProjectsResponse)
@cached_endpoint(prefix="supply:catalogue_projects", expire=1800)
async def list_catalogue_projects(
    limit: int = Query(default=48, ge=1, le=120),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None, max_length=120),
    area: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None, max_length=80),
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_active_subscription),
):
    """List the demo-only supply catalogue."""
    return await list_supply_catalogue_projects(
        db=db,
        limit=limit,
        offset=offset,
        search=search,
        area=area,
        status=status,
    )


@router.get("/catalogue/projects/{project_id}", response_model=SupplyCatalogueProjectDetailResponse)
async def get_catalogue_project(
    project_id: int,
    db: AsyncSession = Depends(get_db_session),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get one demo-only supply catalogue project."""
    return await get_supply_catalogue_project(db, project_id)


@router.get("/catalogue/assets/{asset_id}")
async def get_catalogue_asset(
    asset_id: int,
    download: bool = False,
    db: AsyncSession = Depends(get_db_session),
):
    """Serve locally cached supply catalogue demo assets, downloading from R2 on cache miss.

    Demo note: this is unauthenticated so browser image tags and brochure links work.
    Replace with signed URLs or a real media service before production use.
    """
    path, content_type, name = await get_supply_catalogue_asset_file(db, asset_id)
    return FileResponse(
        path,
        media_type=content_type,
        filename=supply_catalogue_download_filename(asset_id, name, content_type)
        if download
        else None,
    )
