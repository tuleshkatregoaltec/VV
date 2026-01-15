from typing import Optional, List, LiteralString
from datetime import datetime, timezone
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
    users: List[str] = Relationship(back_populates="organization")