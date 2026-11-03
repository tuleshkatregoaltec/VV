"""CRM Assistant: its own conversations, messages and pending lead actions.

Kept apart from market chat (app/chat) so neither surface can list or stream the other's history.
The conversation and message tables date from an earlier assistant (migration c51b90aa7f42);
these models match them, including their index names.
"""

import json
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlmodel import JSON, SQLModel
from sqlmodel import Field as SQLField


class CrmAssistantConversation(SQLModel, table=True):
    __tablename__ = "crm_assistant_conversations"
    __table_args__ = (
        Index("ix_crm_assistant_conversation_owner", "organization_id", "user_id"),
        Index("ix_crm_assistant_conversation_updated_at", "updated_at"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    title: str = SQLField(sa_column=Column(String(200), nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmAssistantMessage(SQLModel, table=True):
    __tablename__ = "crm_assistant_messages"
    __table_args__ = (Index("ix_crm_assistant_message_order", "conversation_id", "created_at"),)

    id: int | None = SQLField(default=None, primary_key=True)
    conversation_id: int = SQLField(
        sa_column=Column(
            Integer,
            ForeignKey("crm_assistant_conversations.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    role: str = SQLField(sa_column=Column(String(20), nullable=False))  # "user" | "assistant"
    content: str = SQLField(sa_column=Column(Text, nullable=False))
    meta_data: dict[str, Any] = SQLField(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


def message_meta(message: CrmAssistantMessage) -> dict[str, Any]:
    """A message's metadata; rows from the earlier assistant hold a list of sources instead."""
    return message.meta_data if isinstance(message.meta_data, dict) else {}


class CrmAssistantAction(SQLModel, table=True):
    """A change the assistant proposed; it runs only when its user confirms it in time."""

    __tablename__ = "crm_assistant_actions"

    id: str = SQLField(primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str = SQLField(index=True)
    conversation_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("crm_assistant_conversations.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    enquiry_id: int = SQLField(index=True)
    action_type: str  # "status" | "note" | "follow_up" | "assign" | "share"
    payload: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    summary: str = SQLField(sa_column=Column(Text, nullable=False))
    before: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    after: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    result: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = SQLField(default="pending", index=True)
    expires_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    resolved_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


# Request/Response Schemas


class CreateAssistantConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class UpdateAssistantConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AssistantMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)


class AssistantConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str | None
    created_at: datetime
    updated_at: datetime


class AssistantConversationListResponse(BaseModel):
    conversations: list[AssistantConversationResponse]
    total: int


class AssistantMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    conversation_id: int
    role: str
    content: str
    meta_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class AssistantActionResult(BaseModel):
    action_id: str
    status: str
    lead_id: int
    href: str | None = None
    text: str | None = None


class AssistantTranscriptResponse(BaseModel):
    """The words in a voice message, for the agent to check before sending. Empty: no speech."""

    text: str


class ActionEdits(BaseModel):
    """The agent's own version of a proposed email, sent with Send email instead of the draft."""

    subject: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


def encode_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, default=str)}\n\n"
