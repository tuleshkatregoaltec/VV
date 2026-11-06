"""Customer-channel persistence and authenticated review contracts; no credentials."""

from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel

from app.whatsapp.models import utcnow


class WhatsAppConnection(SQLModel, table=True):
    __tablename__ = "whatsapp_connections"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    phone_number_id: str = SQLField(unique=True)
    account_id: str
    display_name: str
    enabled: bool = False
    market_data_enabled: bool = False
    approved_knowledge: list[dict[str, str]] = SQLField(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    created_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class WhatsAppCustomerThread(SQLModel, table=True):
    __tablename__ = "whatsapp_customer_threads"
    __table_args__ = (
        UniqueConstraint("connection_id", "sender", name="uq_whatsapp_customer_thread_sender"),
    )

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    connection_id: str = SQLField(
        sa_column=Column(ForeignKey("whatsapp_connections.id", ondelete="CASCADE"), nullable=False)
    )
    sender: str
    paused: bool = False
    opted_out: bool = False
    conversation_id: int | None = SQLField(
        default=None, sa_column=Column(ForeignKey("conversations.id", ondelete="SET NULL"))
    )
    created_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class WhatsAppCustomerMessage(SQLModel, table=True):
    __tablename__ = "whatsapp_customer_messages"
    __table_args__ = (
        Index("ix_whatsapp_customer_message_queue", "status", "send_after"),
        Index("ix_whatsapp_customer_message_thread", "thread_id", "created_at"),
    )

    id: str = SQLField(primary_key=True, max_length=512)
    thread_id: str = SQLField(
        sa_column=Column(
            ForeignKey("whatsapp_customer_threads.id", ondelete="CASCADE"), nullable=False
        )
    )
    content: str | None = SQLField(default=None, sa_column=Column(Text))
    sent_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status: str = "queued"
    reply: str | None = SQLField(default=None, sa_column=Column(Text))
    risk: str | None = None
    topic: str | None = None
    reason: str | None = None
    evidence_ids: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    evidence_snapshots: list[dict] = SQLField(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    revision: int = 1
    send_after: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))
    notification_created_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    notification_seen_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    outbound_id: str | None = None
    error_code: str | None = None


class CustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ApprovedFact(CustomerRequest):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1, max_length=1000)


class KnowledgeUpdate(CustomerRequest):
    approved_knowledge: list[ApprovedFact] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_ids(self):
        if len({fact.id for fact in self.approved_knowledge}) != len(self.approved_knowledge):
            raise ValueError("Knowledge fact IDs must be unique")
        return self


class ConnectionCreate(KnowledgeUpdate):
    approved_knowledge: list[ApprovedFact] = Field(default_factory=list, max_length=20)
    phone_number_id: str = Field(min_length=1, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)


class ConnectionUpdate(CustomerRequest):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    market_data_enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set or any(
            getattr(self, key) is None for key in self.model_fields_set
        ):
            raise ValueError("At least one non-null change is required")
        return self


class RevisionDecision(CustomerRequest):
    expected_revision: int = Field(ge=1)


class ReplyEdit(RevisionDecision):
    reply: str = Field(min_length=1, max_length=4000)


class CustomerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ConnectionResponse(CustomerResponse):
    id: str
    phone_number_id: str
    account_id: str
    display_name: str
    enabled: bool
    market_data_enabled: bool = False
    approved_knowledge: list[ApprovedFact]
    created_at: datetime
    updated_at: datetime


class ThreadResponse(CustomerResponse):
    id: str
    connection_id: str
    sender: str
    paused: bool
    opted_out: bool
    created_at: datetime
    updated_at: datetime


class CustomerMessageResponse(CustomerResponse):
    id: str
    thread_id: str
    content: str | None
    sent_at: datetime
    status: str
    reply: str | None
    risk: str | None
    topic: str | None
    reason: str | None
    evidence_ids: list[str]
    revision: int
    send_after: datetime | None
    notification_created_at: datetime | None
    notification_seen_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WhatsAppPublishedListing(SQLModel, table=True):
    """Explicit broker-approved customer snapshot; never a pointer into private CRM."""

    __tablename__ = "whatsapp_published_listings"
    __table_args__ = (Index("ix_whatsapp_listing_connection", "connection_id", "expires_at"),)

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    connection_id: str = SQLField(
        sa_column=Column(ForeignKey("whatsapp_connections.id", ondelete="CASCADE"), nullable=False)
    )
    title: str
    location: str
    property_type: str
    transaction: str
    bedrooms: int | None = None
    price_aed: float
    area_sqft: float | None = None
    availability: str
    revision: int = 1
    expires_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    revoked_at: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


ListingPropertyType = Literal[
    "apartment", "villa", "townhouse", "penthouse", "office", "land", "other"
]


class PublishedListingCreate(CustomerRequest):
    title: str = Field(min_length=1, max_length=120)
    location: str = Field(min_length=1, max_length=120)
    property_type: ListingPropertyType
    transaction: Literal["sale", "rent"]
    bedrooms: int | None = Field(default=None, ge=0, le=20)
    price_aed: float = Field(
        gt=0,
        le=1_000_000_000,
        allow_inf_nan=False,
        description="Sale asking price or annual asking rent, in AED.",
    )
    area_sqft: float | None = Field(default=None, gt=0, le=10_000_000, allow_inf_nan=False)
    availability: Literal["available", "under_offer", "unavailable"]
    expires_at: AwareDatetime
    approved_for_customer: Literal[True]

    @field_validator("approved_for_customer", mode="before")
    @classmethod
    def explicit_approval(cls, value):
        if value is not True:
            raise ValueError("Explicit customer publication approval is required")
        return value

    @model_validator(mode="after")
    def finite_publication(self):
        if not utcnow() < self.expires_at <= utcnow() + timedelta(days=30):
            raise ValueError("Publication must expire in the next 30 days")
        if any(not value.isprintable() for value in (self.title, self.location)):
            raise ValueError("Listing labels must be plain single-line text")
        return self


class PublishedListingUpdate(PublishedListingCreate):
    expected_revision: int = Field(ge=1)


class PublishedListingResponse(CustomerResponse):
    id: str
    connection_id: str
    title: str
    location: str
    property_type: ListingPropertyType
    transaction: Literal["sale", "rent"]
    bedrooms: int | None
    price_aed: float
    area_sqft: float | None
    availability: Literal["available", "under_offer", "unavailable"]
    revision: int
    expires_at: datetime
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime
