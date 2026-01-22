# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
from typing import List

from sqlalchemy.orm import selectinload
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.postgres.models import Project


async def get_upcoming_projects(db: AsyncSession) -> List[Project]:
    """
    Get all active/upcoming projects.
    Active = has start_date AND no completion_date AND no cancellation_date
    """
    stmt = (
        select(Project)
        .options(selectinload(Project.developer), selectinload(Project.area))
        .where(
            Project.project_start_date.isnot(None),
            Project.completion_date.is_(None),
            Project.cancellation_date.is_(None),
        )
        .order_by(
            Project.project_end_date.asc().nulls_last(), Project.project_name_en.asc()
        )
    )
    result = await db.exec(stmt)
    return list(result.all())
