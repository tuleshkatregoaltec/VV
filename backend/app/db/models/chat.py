from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from sqlalchemy import Text, DateTime
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, LiteralString


class Conversation(SQLModel, table=True):
    __tablename__: LiteralString = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    title: Optional[str] = None
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    messages: List["Message"] = Relationship(back_populates="conversation")


class Message(SQLModel, table=True):
    __tablename__: LiteralString = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # "user" | "assistant"
    content: str = Field(sa_column=Column(Text))

    meta_data: Optional[Dict[str, Any]] = Field(sa_column=Column(JSON), default={})

    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    conversation: Optional[Conversation] = Relationship(back_populates="messages")
