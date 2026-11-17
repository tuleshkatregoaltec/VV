from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WhatsAppTurn(SQLModel, table=True):
    """Durable single-pilot receipt and outbound ledger; identity is server assigned."""

    __tablename__ = "whatsapp_turns"
    __table_args__ = (Index("ix_whatsapp_turns_queue", "status", "created_at"),)

    id: str = Field(primary_key=True, max_length=512)
    phone_number_id: str
    sender: str
    user_id: str = Field(index=True)
    organization_id: str = Field(index=True)
    content: str = Field(sa_column=Column(Text, nullable=False))
    sent_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status: str = "queued"
    conversation_id: int | None = Field(
        default=None, sa_column=Column(ForeignKey("conversations.id", ondelete="SET NULL"))
    )
    reply: str | None = Field(default=None, sa_column=Column(Text))
    outbound_id: str | None = Field(default=None, index=True)
    error_code: str | None = None
