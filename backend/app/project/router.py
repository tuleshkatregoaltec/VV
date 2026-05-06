from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.decorators import cached_endpoint
from app.core.dependencies import AuthContext, require_active_subscription
from app.project.models import (
    BuildingDetailResponse,
    DDAOutlineFeature,
    DDAPlotFeature,
    MasterProjectResponse,
    ProjectDetailResponse,
    ProjectRadarResponse,
    ProjectSearchResult,
)
from app.project.service import (
    get_building_details,
    get_dda_outlines_for_bounds,
    get_dda_plots_for_area,
    get_master_project,
    get_project_details,
    get_project_radar,
    list_all_projects,
)

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("/list", response_model=List[ProjectSearchResult])
@cached_endpoint(prefix="project_list", expire=3600)  # 1 hour
async def list_projects(context: AuthContext = Depends(require_active_subscription)):
    """Get all projects for client-side search"""
    return await list_all_projects()


@router.get("/radar", response_model=ProjectRadarResponse)
@cached_endpoint(prefix="project_radar", expire=1800)
async def project_radar(
    limit: int = Query(default=1400, ge=100, le=3000, description="Maximum mapped projects"),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get mapped project, area, and planning signals for the radar view."""
    return await get_project_radar(limit=limit)


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
    area: Optional[str] = Query(None, description="Area or community name to match against DDA plots"),
    west: Optional[float] = Query(None, ge=54, le=57, description="Viewport west longitude"),
    south: Optional[float] = Query(None, ge=24, le=26, description="Viewport south latitude"),
    east: Optional[float] = Query(None, ge=54, le=57, description="Viewport east longitude"),
    north: Optional[float] = Query(None, ge=24, le=26, description="Viewport north latitude"),
    limit: int = Query(default=1200, ge=100, le=5000, description="Maximum DDA plots to return"),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get DDA GIS plot polygons for a community or current map viewport."""
    return await get_dda_plots_for_area(
        area=area,
        west=west,
        south=south,
        east=east,
        north=north,
        limit=limit,
    )


@router.get("/dda-outlines", response_model=List[DDAOutlineFeature])
@cached_endpoint(prefix="dda_outlines", expire=3600)
async def get_dda_outlines(
    west: float = Query(..., ge=54, le=57, description="Viewport west longitude"),
    south: float = Query(..., ge=24, le=26, description="Viewport south latitude"),
    east: float = Query(..., ge=54, le=57, description="Viewport east longitude"),
    north: float = Query(..., ge=24, le=26, description="Viewport north latitude"),
    zoom: float = Query(..., ge=1, le=22, description="Current map zoom"),
    limit: int = Query(default=160, ge=20, le=500, description="Maximum outlines to return"),
    context: AuthContext = Depends(require_active_subscription),
):
    """Get coarse DDA planning outlines for low-zoom map context."""
    return await get_dda_outlines_for_bounds(
        west=west,
        south=south,
        east=east,
        north=north,
        zoom=zoom,
        limit=limit,
    )


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
