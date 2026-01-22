from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.postgres import get_db_session
from app.services import projects_service
from app.schemas.projects import ProjectSearchResult, ProjectDetailResponse
from app.core.decorators import cached_endpoint
from typing import List

router = APIRouter(prefix="/api/v1/projects", tags=["projects"])


@router.get("/list", response_model=List[ProjectSearchResult])
@cached_endpoint(prefix="project_list", expire=3600)  # 1 hour
async def list_projects(db: AsyncSession = Depends(get_db_session)):
    """Get all projects for client-side search"""
    return await projects_service.list_all_projects(db)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
@cached_endpoint(prefix="project_details", expire=1800)  # 30 minutes
async def get_project_details(
    project_id: int, db: AsyncSession = Depends(get_db_session)
):
    """Get full project details with unit composition"""
    project = await projects_service.get_project_details(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
