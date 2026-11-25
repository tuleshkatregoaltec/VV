from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, LiteralString, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlmodel import JSON, Column, Field, Relationship, SQLModel

# The chat product a conversation belongs to: the CRM Operations Assistant or Market AI (/chat).
ChatAssistant = Literal["crm", "market"]


class Conversation(SQLModel, table=True):
    __tablename__: LiteralString = "conversations"
    __table_args__ = (
        CheckConstraint("assistant IN ('crm', 'market')", name="ck_conversations_assistant"),
        # Each product lists its own history: newest first, per owner.
        Index("ix_conversations_owner_assistant", "user_id", "organization_id", "assistant"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    title: Optional[str] = None
    # Set when created and never changed: a conversation belongs to one assistant.
    assistant: str = Field(
        default="crm",
        sa_column=Column(String, nullable=False, server_default="crm"),
    )
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


class ChatTurnLease(SQLModel, table=True):
    """An expiring capacity lease whose token reservation survives process loss."""

    __tablename__ = "chat_turn_leases"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    conversation_id: int = Field(index=True)
    budget_day: date
    reserved_tokens: int
    status: str = "active"
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    finished_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))


# Request/Response Schemas


class CreateConversationRequest(BaseModel):
    """Request model for creating a new conversation"""

    title: Optional[str] = None
    # Which product's history it belongs to; the CRM Operations Assistant when omitted.
    assistant: ChatAssistant = "crm"


class SendMessageRequest(BaseModel):
    """Request model for sending a message in a conversation"""

    message: str = Field(min_length=1, max_length=8000)


class TranscriptResponse(BaseModel):
    """The words in a voice message, for the agent to check before sending. Empty: no speech."""

    text: str


class UpdateConversationRequest(BaseModel):
    """Request model for updating a conversation"""

    title: str


class ConversationResponse(BaseModel):
    """Response model for conversation data"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: str
    title: Optional[str]
    assistant: ChatAssistant = "crm"
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(BaseModel):
    """Response model for list of conversations"""

    conversations: List[ConversationResponse]
    total: int


class MessageResponse(BaseModel):
    """Response model for message data"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    meta_data: Optional[Dict[str, Any]] = None
    created_at: datetime
