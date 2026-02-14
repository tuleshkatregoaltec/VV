from fastapi import APIRouter, Depends, HTTPException
from app.project.service import list_all_projects, get_project_details, get_building_details
from app.project.models import ProjectSearchResult, ProjectDetailResponse, BuildingDetailResponse
from app.core.decorators import cached_endpoint
from app.core.dependencies import require_active_subscription, AuthContext
from typing import List

router = APIRouter(
    prefix="/api/v1/projects",
    tags=["projects"],
)


@router.get("/list", response_model=List[ProjectSearchResult])
@cached_endpoint(prefix="project_list", expire=3600)  # 1 hour
async def list_projects(context: AuthContext = Depends(require_active_subscription)):
    """Get all projects for client-side search"""
    return await list_all_projects()


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
