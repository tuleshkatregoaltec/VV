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
        from app.core.ai_policy import reserved_daily_tokens

        today = datetime.now(timezone.utc).date()
        legacy = await repository.get_usage(db, user_id, today)
        accounted = await reserved_daily_tokens(user_id, today)
        if not accounted:
            return legacy
        # Existing PostgreSQL totals predate the shared provider ledger. Include
        # both during the cutover; new calls must never also call record_usage.
        return UserTokenUsage(
            user_id=user_id,
            date=today,
            total_tokens=accounted + (legacy.total_tokens if legacy else 0),
            prompt_tokens=legacy.prompt_tokens if legacy else 0,
            completion_tokens=legacy.completion_tokens if legacy else 0,
        )

    async def create_usage_record(
        self,
        db: AsyncSession,
        user_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        today = date.today()
        now = datetime.now(timezone.utc)

        usage = UserTokenUsage(
            user_id=user_id,
            date=today,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            created_at=now,
            updated_at=now,
        )

        repository.save(db, usage)
        await db.commit()
        await db.refresh(usage)
        return usage

    async def update_usage_record(
        self,
        db: AsyncSession,
        usage_record: UserTokenUsage,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        usage_record.prompt_tokens += prompt_tokens
        usage_record.completion_tokens += completion_tokens
        usage_record.total_tokens += total_tokens
        usage_record.updated_at = datetime.now(timezone.utc)

        repository.save(db, usage_record)
        await db.commit()
        await db.refresh(usage_record)
        return usage_record

    async def record_usage(
        self,
        db: AsyncSession,
        user_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> UserTokenUsage:
        from sqlalchemy import text

        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"token-usage:{user_id}:{datetime.now(timezone.utc).date()}"},
        )
        existing = await repository.get_usage(db, user_id, datetime.now(timezone.utc).date())

        if existing:
            # Update existing record
            return await self.update_usage_record(
                db, existing, prompt_tokens, completion_tokens, total_tokens
            )
        else:
            # Create new record
            return await self.create_usage_record(
                db, user_id, prompt_tokens, completion_tokens, total_tokens
            )

    async def update_user_limit(self, user_id: str, new_limit: int) -> None:
        await update_user_token_limit(user_id, new_limit)

    async def get_usage_records(
        self, db: AsyncSession, day: date, user_ids: list[str] | None = None
    ):
        return await repository.get_usage_records(db, day, user_ids)


token_usage_service = TokenUsageService()
