from datetime import date, datetime, timezone

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.token_usage.models import UserTokenUsage


async def get_usage(db: AsyncSession, user_id: str, day: date):
    stmt = select(UserTokenUsage).where(
        UserTokenUsage.user_id == user_id, UserTokenUsage.date == day
    )
    result = await db.exec(stmt)
    return result.first()


async def get_usage_records(db: AsyncSession, day: date, user_ids: list[str] | None = None):
    stmt = select(UserTokenUsage).where(UserTokenUsage.date == day)
    if user_ids is not None:
        stmt = stmt.where(UserTokenUsage.user_id.in_(user_ids))
    result = await db.execute(stmt)
    return result.scalars().all()


def save(db: AsyncSession, usage: UserTokenUsage):
    db.add(usage)


async def increment(db, user_id, day, prompt_tokens, completion_tokens, total_tokens):
    """Atomic counters; caller owns commit so reservations and usage cannot separate."""
    now = datetime.now(timezone.utc)
    statement = insert(UserTokenUsage).values(
        user_id=user_id,
        date=day,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        created_at=now,
        updated_at=now,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_user_token_usage_day",
        set_={
            "prompt_tokens": UserTokenUsage.prompt_tokens + prompt_tokens,
            "completion_tokens": UserTokenUsage.completion_tokens + completion_tokens,
            "total_tokens": UserTokenUsage.total_tokens + total_tokens,
            "updated_at": now,
        },
    ).returning(UserTokenUsage)
    result = await db.execute(statement.execution_options(populate_existing=True))
    return result.scalar_one()
