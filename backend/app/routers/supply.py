from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session
from typing import List

from backend.app.db.session import get_db_session
from backend.app.services.auth_service import get_current_user
from backend.app.db.models import User, Developer, Project
from backend.app.core.decorators import cached_endpoint

from backend.app.services.supply_service import (
    get_all_developers,
    get_developer_by_id,
    get_projects_by_developer,
    get_project_details
)

router = APIRouter(
    prefix="/supply",
    tags=["supply"]
)

@router.get("/developers", response_model=List[Developer])
@cached_endpoint(prefix="developers", expire=3600)
async def list_developers(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=1000),
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    return get_all_developers(session, skip=skip, limit=limit)

@router.get("/developers/{developer_id}", response_model=Developer)
@cached_endpoint(prefix="developer", expire=3600)
async def get_developer(
    developer_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    developer = get_developer_by_id(session, developer_id)
    if not developer:
        raise HTTPException(status_code=404, detail="Developer not found")
    return developer

@router.get("/developers/{developer_id}/projects", response_model=List[Project])
@cached_endpoint(prefix="developer_projects", expire=1800)
async def list_developer_projects(
    developer_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    return get_projects_by_developer(session, developer_id)

@router.get("/projects/{project_id}", response_model=Project)
@cached_endpoint(prefix="project", expire=3600)
async def get_project(
    project_id: int,
    session: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user)
):
    project = get_project_details(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
