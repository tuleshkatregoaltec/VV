from typing import Optional, LiteralString
from datetime import datetime, timezone, date as dt_date
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, DateTime


class UserTokenUsage(SQLModel, table=True):
    """Daily token usage tracking per user"""

    __tablename__: LiteralString = "user_token_usage"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key to user
    user_id: str = Field(index=True)

    # Usage tracking
    date: dt_date = Field(index=True)  # UTC date
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    total_tokens: int = Field(default=0)

    # Timestamps
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
