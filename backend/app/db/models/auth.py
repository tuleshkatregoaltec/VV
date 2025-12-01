from typing import Optional, List, LiteralString
from datetime import datetime, timezone
from sqlmodel import SQLModel, Field, Relationship
from sqlalchemy import Column, DateTime

class Organisation(SQLModel, table=True):
    __tablename__: LiteralString = "organisations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organisation details
    name: str = Field(index=True)
    email_domain: str = Field(unique=True, index=True)
    max_users: int = Field(default=5)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    users: List["User"] = Relationship(back_populates="organisation")


class User(SQLModel, table=True):
    __tablename__: LiteralString = "users"

    # Primary key
    id: str = Field(primary_key=True)

    # User details
    email: str = Field(unique=True, index=True)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organisation_id: Optional[str] = Field(default=None, foreign_key="organisations.id")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False), default_factory=lambda: datetime.now(timezone.utc))
    last_login: datetime = Field(sa_column=Column(DateTime(timezone=True)), default_factory=lambda: datetime.now(timezone.utc))

    # Relationships
    organisation: Optional["Organisation"] = Relationship(back_populates="users")
