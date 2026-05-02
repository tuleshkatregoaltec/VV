from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.project.models import (
    BuildingDetailResponse,
    DDAPlotFeature,
    MasterProjectResponse,
    ProjectDetailResponse,
    ProjectSearchResult,
)
from app.project.service import (
    get_building_details,
    get_dda_plots_for_area,
    get_master_project,
    get_project_details,
    list_all_projects,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("/list", response_model=List[ProjectSearchResult])
@cached_endpoint(prefix="project_list", expire=3600)  # 1 hour
async def list_projects(context: AuthContext = Depends(require_active_subscription)):
    """Get all projects for client-side search"""
    return await list_all_projects()


@router.get("/master", response_model=MasterProjectResponse)
@cached_endpoint(prefix="master_project", expire=1800)  # 30 minutes
async def master_project(
    name: str = Query(..., description="master_project_en value"),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get aggregated data for a master project and its sub-projects"""
    master = await get_master_project(name)
    if not master:
        raise HTTPException(status_code=404, detail="Master project not found")
    return master


@router.get("/building/{property_id}", response_model=BuildingDetailResponse)
@cached_endpoint(prefix="building_details", expire=1800)  # 30 minutes
async def building_details(
    property_id: int, context: AuthContext = Depends(require_active_subscription)
):
    """Get building details with unit composition by bedroom type"""
    building = await get_building_details(property_id)
    if not building:
        raise HTTPException(status_code=404, detail="Building not found")
    return building


@router.get("/dda-plots", response_model=List[DDAPlotFeature])
@cached_endpoint(prefix="dda_plots", expire=3600)  # 1 hour — plot data changes rarely
async def get_dda_plots(
    area: str = Query(..., description="Area or community name to match against DDA plots"),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get DDA GIS plot polygons for a given area/community for map overlay."""
    return await get_dda_plots_for_area(area)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
@cached_endpoint(prefix="project_details", expire=1800)  # 30 minutes
async def project_details(
    project_id: int, context: AuthContext = Depends(require_active_subscription)
):
    """Get full project details with unit composition"""
    project = await get_project_details(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
