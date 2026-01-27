import logging
from datetime import date
from typing import List

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.dependencies import require_admin
from app.postgres import get_db_session
from app.token_usage.models import UserTokenUsage, UserTokenStatsResponse
from app.auth.service import get_user_by_id

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/token-usage", response_model=List[UserTokenStatsResponse])
async def list_token_usage(
    db: AsyncSession = Depends(get_db_session), _admin: None = Depends(require_admin)
):
    """Admin: list today's token usage for all users."""
    today = date.today()
    stmt = select(UserTokenUsage).where(UserTokenUsage.date == today)
    result = await db.exec(stmt)
    usages = result.all()

    out: List[UserTokenStatsResponse] = []
    for usage in usages:
        user = await get_user_by_id(usage.user_id)
        daily_limit = getattr(user.app_metadata, "daily_token_limit", 0) if user else 0
        tokens_used = usage.total_tokens if usage else 0
        remaining = max(0, daily_limit - tokens_used)
        usage_percentage = (tokens_used / daily_limit * 100) if daily_limit > 0 else 0.0

        out.append(
            UserTokenStatsResponse(
                user_id=usage.user_id,
                tokens_used_today=tokens_used,
                daily_limit=daily_limit,
                usage_percentage=usage_percentage,
                remaining_tokens=remaining,
            )
        )

    return out
