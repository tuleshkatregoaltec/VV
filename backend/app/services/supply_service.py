from typing import Sequence, Optional  # Import Sequence instead of/alongside List
from sqlmodel import Session, select
from backend.app.db.models import Developer, Project

def get_all_developers(session: Session, skip: int = 0, limit: int = 100) -> Sequence[Developer]:
    statement = select(Developer).offset(skip).limit(limit)
    return session.exec(statement).all()

def get_developer_by_id(session: Session, developer_id: int) -> Optional[Developer]:
    return session.get(Developer, developer_id)

def get_projects_by_developer(session: Session, developer_id: int) -> Sequence[Project]:
    statement = (
        select(Project)
        .where(Project.developer_id == developer_id)
        .order_by(Project.project_status)
    )
    return session.exec(statement).all()

def get_project_details(session: Session, project_id: int) -> Optional[Project]:
    return session.get(Project, project_id)
