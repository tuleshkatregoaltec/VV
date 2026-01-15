import logging
from datetime import date, datetime, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.models.auth import User, UserTokenUsage

logger = logging.getLogger(__name__)


class TokenUsageService:

    async def get_today_usage(
        self, db: AsyncSession, user_id: str
    ) -> Optional[UserTokenUsage]:

        today = date.today()
        stmt = select(UserTokenUsage).where(
            UserTokenUsage.user_id == user_id, UserTokenUsage.date == today
        )
        result = await db.exec(stmt)
        return result.first()

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

        db.add(usage)
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

        db.add(usage_record)
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

        existing = await self.get_today_usage(db, user_id)

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

    async def update_user_limit(
        self, db: AsyncSession, user_id: str, new_limit: int
    ) -> User:

        user = await db.get(User, user_id)

        if not user:
            raise ValueError(f"User {user_id} not found")

        user.daily_token_limit = new_limit
        user.updated_at = datetime.now(timezone.utc)

        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


token_usage_service = TokenUsageService()
