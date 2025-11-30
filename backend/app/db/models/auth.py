from typing import Optional, List, LiteralString
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship

class Organisation(SQLModel, table=True):
    __tablename__: LiteralString = "organisations"

    # Primary key
    id: str = Field(primary_key=True)

    # Organisation details
    name: str = Field(index=True)
    email_domain: str = Field(unique=True, index=True)
    max_users: int = Field(default=5)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

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
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    last_login: datetime = Field(default_factory=datetime.now)

    # Relationships
    organisation: Optional["Organisation"] = Relationship(back_populates="users")
