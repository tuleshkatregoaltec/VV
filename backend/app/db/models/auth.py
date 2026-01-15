from typing import Optional, List, LiteralString
from datetime import datetime, timezone, date
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime


class Organization(SQLModel, table=True):
    """Organization model for multi-tenancy with WorkOS integration"""

    __tablename__: LiteralString = "organizations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organization details
    name: str = Field(index=True)
    email_domain: str = Field(unique=True, index=True)
    max_users: int = Field(default=5)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    users: List["User"] = Relationship(back_populates="organization")


class User(SQLModel, table=True):
    """User model linked to Organization with WorkOS authentication"""

    __tablename__: LiteralString = "users"

    # Primary key
    id: str = Field(primary_key=True)

    # User details
    email: str = Field(unique=True, index=True)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_id: Optional[str] = Field(default=None, foreign_key="organizations.id")
    role: str = Field(default="user")
    is_active: bool = Field(default=True)
    daily_token_limit: int = Field(default=100000)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    last_login: datetime = Field(
        sa_column=Column(DateTime(timezone=True)),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    organization: Optional["Organization"] = Relationship(back_populates="users")


class UserTokenUsage(SQLModel, table=True):
    """Daily token usage tracking per user"""

    __tablename__: LiteralString = "user_token_usage"

    # Primary key
    id: Optional[int] = Field(default=None, primary_key=True)

    # Foreign key to user
    user_id: str = Field(foreign_key="users.id", index=True)

    # Usage tracking
    date: date = Field(index=True)  # UTC date
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
