# pyright: reportArgumentType=false, reportCallIssue=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false
from datetime import date
from typing import Dict, List, Literal, Optional

from sqlalchemy.orm import selectinload
from sqlmodel import String, and_, case, cast, col, desc, func, or_, select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.db.models import Developer, Project
from backend.app.db.models.transactions import Transaction


# Status constants
ACTIVE_STATUSES = {"IN PROGRESS", "UNDER CONSTRUCTION"}
COMPLETED_STATUSES = {"COMPLETED", "FINISHED"}

SortOption = Literal["projects", "transactions", "avg_price"]


async def get_developer_count(db: AsyncSession) -> int:
    """Get total count of developers."""
    result = await db.exec(select(func.count()).select_from(Developer))
    return result.one()


async def get_all_developers(
    db: AsyncSession,
    sort_by: SortOption = "projects",
    limit: int | None = None,
    offset: int = 0,
) -> List[Developer]:
    """Get developers sorted by criteria with optional pagination."""

    if sort_by == "transactions":
        tx_count = (
            select(
                Project.developer_id,
                func.count(Transaction.transaction_id).label("tx_count"),
            )
            .join(
                Transaction,
                cast(Project.project_number, String) == Transaction.project_number,
            )
            .group_by(Project.developer_id)
            .subquery()
        )
        stmt = (
            select(Developer)
            .outerjoin(tx_count, Developer.developer_id == tx_count.c.developer_id)
            .order_by(
                desc(func.coalesce(tx_count.c.tx_count, 0)), Developer.developer_name_en
            )
        )
    elif sort_by == "avg_price":
        avg_price = (
            select(
                Project.developer_id,
                func.avg(Transaction.actual_worth).label("avg_worth"),
            )
            .join(
                Transaction,
                cast(Project.project_number, String) == Transaction.project_number,
            )
            .where(Transaction.actual_worth > 0)
            .group_by(Project.developer_id)
            .subquery()
        )
        stmt = (
            select(Developer)
            .outerjoin(avg_price, Developer.developer_id == avg_price.c.developer_id)
            .order_by(
                desc(func.coalesce(avg_price.c.avg_worth, 0)),
                Developer.developer_name_en,
            )
        )
    else:
        total_count = (
            select(Project.developer_id, func.count(Project.project_id).label("total"))
            .group_by(Project.developer_id)
            .subquery()
        )
        stmt = (
            select(Developer)
            .outerjoin(
                total_count, Developer.developer_id == total_count.c.developer_id
            )
            .order_by(
                desc(func.coalesce(total_count.c.total, 0)), Developer.developer_name_en
            )
        )

    if limit is not None:
        stmt = stmt.offset(offset).limit(limit)

    result = await db.exec(stmt)
    return list(result.all())


async def get_developer_by_id(
    db: AsyncSession, developer_id: int
) -> Optional[Developer]:
    """Get developer by ID"""
    return await db.get(Developer, developer_id)


async def get_developer_stats_bulk(
    db: AsyncSession, developer_ids: List[int]
) -> Dict[int, dict]:
    """Get project stats for multiple developers in one query."""
    if not developer_ids:
        return {}

    today = date.today()
    upper_status = func.upper(func.coalesce(Project.project_status, ""))

    # Cancelled: past cancellation_date OR status is CANCELLED
    is_cancelled = or_(
        and_(
            Project.cancellation_date.isnot(None),
            col(Project.cancellation_date) < today,
        ),
        upper_status == "CANCELLED",
    )

    # Completed: not cancelled AND (past completion_date OR completed status)
    is_completed = and_(
        ~is_cancelled,
        or_(
            and_(
                Project.completion_date.isnot(None),
                col(Project.completion_date) < today,
            ),
            upper_status.in_(COMPLETED_STATUSES),
        ),
    )

    # Active: not cancelled, not completed, has active status
    is_active = and_(~is_cancelled, ~is_completed, upper_status.in_(ACTIVE_STATUSES))

    stmt = (
        select(
            Project.developer_id,
            func.count().label("total"),
            func.sum(case((is_cancelled, 1), else_=0)).label("cancelled"),
            func.sum(case((is_completed, 1), else_=0)).label("completed"),
            func.sum(case((is_active, 1), else_=0)).label("active"),
        )
        .where(col(Project.developer_id).in_(developer_ids))
        .group_by(Project.developer_id)
    )

    result = await db.exec(stmt)
    rows = result.all()

    # Initialize with zeros, then populate from query results
    stats_map = {
        dev_id: {"total": 0, "active": 0, "completed": 0, "cancelled": 0}
        for dev_id in developer_ids
    }
    for row in rows:
        stats_map[row.developer_id] = {
            "total": row.total or 0,
            "active": int(row.active or 0),
            "completed": int(row.completed or 0),
            "cancelled": int(row.cancelled or 0),
        }

    return stats_map


async def get_projects_by_developer(
    db: AsyncSession, developer_id: int
) -> List[Project]:
    """Get projects for a developer, active first, then by completion %."""
    stmt = (
        select(Project)
        .options(selectinload(Project.area))
        .where(Project.developer_id == developer_id)
        .order_by(
            desc(func.upper(Project.project_status).in_(list(ACTIVE_STATUSES))),
            desc(func.coalesce(Project.percent_completed, -1)),
            Project.project_name,
        )
    )
    result = await db.exec(stmt)
    return list(result.all())


async def get_project_by_id(db: AsyncSession, project_id: int) -> Optional[Project]:
    """Get project with area."""
    stmt = (
        select(Project)
        .options(selectinload(Project.area))
        .where(Project.project_id == project_id)
    )
    result = await db.exec(stmt)
    return result.first()
