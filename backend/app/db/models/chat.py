from sqlmodel import SQLModel, Field, Relationship, Column, JSON
from sqlalchemy import Text, DateTime
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


class Conversation(SQLModel, table=True):
    """Chat conversation belonging to a user"""

    __tablename__ = "conversations"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: str = Field(foreign_key="users.id", index=True)  # WorkOS uses string IDs
    title: Optional[str] = None  # Auto-generated from first message
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    messages: List["Message"] = Relationship(
        back_populates="conversation", cascade_delete=True
    )
    tool_calls: List["ToolCallResult"] = Relationship(
        back_populates="conversation", cascade_delete=True
    )


class Message(SQLModel, table=True):
    """Individual message in a conversation with optional compression"""

    __tablename__ = "messages"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    role: str  # "user" | "assistant" | "system"
    content: str = Field(sa_column=Column(Text))  # Full content
    compressed_content: Optional[str] = Field(
        sa_column=Column(Text), default=None
    )  # LLMLingua compressed
    compression_ratio: Optional[float] = None  # Track compression effectiveness
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Tool call reference (if this message triggered tools)
    tool_call_ids: Optional[List[int]] = Field(sa_column=Column(JSON), default=None)

    # Relationship
    conversation: Optional[Conversation] = Relationship(back_populates="messages")


class ToolCallResult(SQLModel, table=True):
    """Stores LLM tool call execution results with caching metadata"""

    __tablename__ = "tool_call_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversations.id", index=True)
    message_id: Optional[int] = Field(
        foreign_key="messages.id", index=True, default=None
    )  # Message that triggered it

    # Tool information
    tool_name: str  # e.g., "get_sales_analytics"
    tool_args: Dict[str, Any] = Field(sa_column=Column(JSON))  # Arguments passed

    # Result
    result: Dict[str, Any] = Field(sa_column=Column(JSON))  # Tool response
    error: Optional[str] = None  # If tool call failed

    # Metadata
    execution_time_ms: Optional[int] = None
    cached: bool = Field(default=False)  # Whether result came from cache
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        default_factory=lambda: datetime.now(timezone.utc),
    )

    # Relationship
    conversation: Optional[Conversation] = Relationship(back_populates="tool_calls")
