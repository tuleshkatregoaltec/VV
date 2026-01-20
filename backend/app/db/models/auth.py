from typing import Optional, List, LiteralString
from datetime import datetime, timezone
import datetime as dt
from sqlmodel import SQLModel, Field, Relationship, JSON
from sqlalchemy import Column, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableList


class Organization(SQLModel, table=True):
    """Organization model for multi-tenancy with WorkOS integration"""

    __tablename__: LiteralString = "organizations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organization details
    name: str
    max_users: int = Field(default=5)
    is_active: bool = Field(default=True)
    organization_admin_id: str  # User ID of org admin

    # Payment and subscription tracking
    status: str = Field(
        default="active"
    )  # "pending_payment", "active", "canceled"
    stripe_checkout_session_id: Optional[str] = Field(
        default=None, unique=True, index=True
    )

    # Stripe integration
    subscription_id: Optional[str] = Field(default=None, foreign_key="subscriptions.id")
    stripe_customer_id: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    users: list[str] = Field(
        default=[], sa_column=Column(MutableList.as_mutable(JSONB))
    )


class UserTokenUsage(SQLModel, table=True):
    """Daily token usage tracking per user"""

    __tablename__: LiteralString = "user_token_usage"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key to user
    user_id: str = Field(index=True)

    # Usage tracking
    date: dt.date = Field(index=True)  # UTC date
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
