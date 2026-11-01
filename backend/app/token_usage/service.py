import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.service import update_user_token_limit
from app.token_usage import repository
from app.token_usage.models import UserTokenUsage

logger = logging.getLogger(__name__)


class TokenUsageService:
    async def get_today_usage(self, db: AsyncSession, user_id: str) -> Optional[UserTokenUsage]:
        return await repository.get_usage(db, user_id, datetime.now(timezone.utc).date())

    async def create_usage_record(
        self,
        db: AsyncSession,
        user_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        return await self.record_usage(db, user_id, prompt_tokens, completion_tokens, total_tokens)

    async def update_usage_record(
        self,
        db: AsyncSession,
        usage_record: UserTokenUsage,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        usage = await repository.increment(
            db,
            usage_record.user_id,
            usage_record.date,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        await db.commit()
        return usage

    async def record_usage(
        self,
        db: AsyncSession,
        user_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        usage = await repository.increment(
            db,
            user_id,
            datetime.now(timezone.utc).date(),
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )
        await db.commit()
        return usage

    async def update_user_limit(self, user_id: str, new_limit: int) -> None:
        await update_user_token_limit(user_id, new_limit)

    async def get_usage_records(
        self, db: AsyncSession, day: date, user_ids: list[str] | None = None
    ):
        return await repository.get_usage_records(db, day, user_ids)


token_usage_service = TokenUsageService()
