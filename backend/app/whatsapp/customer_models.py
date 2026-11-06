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
    account_id: str = SQLField(index=True)  # WABA ID; webhook entries route by it
    display_name: str
    enabled: bool = False
    market_data_enabled: bool = False
    approved_knowledge: list[dict[str, str]] = SQLField(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    # Per-agent Meta asset state. `enabled` remains the agent's automation switch.
    status: str = "connected"  # connected | disconnected
    onboarding_type: str | None = None  # coexistence | cloud_api | env
    business_id: str | None = None
    display_phone_number: str | None = None
    # Fernet ciphertext only; plaintext business tokens never reach the database.
    access_token_encrypted: str | None = SQLField(default=None, sa_column=Column(Text), repr=False)
    quality_rating: str | None = None
    health: dict | None = SQLField(default=None, sa_column=Column(JSON))
    last_account_event: str | None = None
    connected_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    disconnected_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    contacts_sync_requested_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    contacts_synced_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )
    created_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = SQLField(
        default_factory=utcnow, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class WhatsAppContact(SQLModel, table=True):
    """Address-book entry synced from the agent's WhatsApp Business app, or a manual block."""

    __tablename__ = "whatsapp_contacts"
    __table_args__ = (
        UniqueConstraint("connection_id", "wa_id", name="uq_whatsapp_contact_wa_id"),
        UniqueConstraint("connection_id", "bsuid", name="uq_whatsapp_contact_bsuid"),
        Index("ix_whatsapp_contact_blocked", "connection_id", "blocked"),
    )

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    connection_id: str = SQLField(
        sa_column=Column(ForeignKey("whatsapp_connections.id", ondelete="CASCADE"), nullable=False)
    )
    wa_id: str | None = None  # digits only, as Meta sends `from`
    bsuid: str | None = None  # business-scoped user id, when Meta provides one
    name: str | None = None
    in_address_book: bool = True
    blocked: bool = False
    blocked_at: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))
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


# ─── Embedded Signup and per-agent connection contract ──────────────────────────

SignupEvent = Literal["FINISH", "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING", "FINISH_ONLY_WABA"]


class SignupConfigResponse(BaseModel):
    """Public values for FB.init/FB.login. `configured` is false until Meta is set up."""

    configured: bool
    missing: list[str]
    app_id: str | None
    config_id: str | None
    graph_api_version: str | None
    extras: dict
    state: str | None


class SignupComplete(CustomerRequest):
    state: str = Field(min_length=1, max_length=512)
    code: str = Field(min_length=1, max_length=2048)
    phone_number_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^\d+$")
    waba_id: str = Field(min_length=1, max_length=64, pattern=r"^\d+$")
    business_id: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^\d+$")
    event: SignupEvent


class AutomationToggle(CustomerRequest):
    enabled: bool


class ContactCounts(BaseModel):
    total: int
    blocked: int
    sync_requested_at: datetime | None
    synced_at: datetime | None


class AgentConnectionStatus(BaseModel):
    """State of the signed-in agent's WhatsApp number.

    state: not_configured (Meta setup missing on the server), not_connected,
    connected, disconnected.
    """

    state: Literal["not_configured", "not_connected", "connected", "disconnected"]
    signup_configured: bool
    connection_id: str | None = None
    phone_number_id: str | None = None
    waba_id: str | None = None
    business_id: str | None = None
    display_phone_number: str | None = None
    display_name: str | None = None
    onboarding_type: str | None = None
    automation_enabled: bool = False
    connected_at: datetime | None = None
    disconnected_at: datetime | None = None
    last_account_event: str | None = None
    quality_rating: str | None = None
    # Meta's phone-number health_status: can_send_message is AVAILABLE, LIMITED or BLOCKED.
    can_send_message: str | None = None
    health_errors: list[dict] = Field(default_factory=list)
    # Replies are billed to the agent's own WABA payment method; Meta does not tell a
    # Tech Provider whether one is on file, so this stays "unknown".
    payment_method_status: Literal["unknown"] = "unknown"
    contacts: ContactCounts | None = None


class ContactResponse(CustomerResponse):
    id: str
    wa_id: str | None
    name: str | None
    in_address_book: bool
    blocked: bool
    blocked_at: datetime | None
    updated_at: datetime


class ContactPage(BaseModel):
    items: list[ContactResponse]
    total: int
    limit: int
    offset: int


class BlockRequest(CustomerRequest):
    contact_ids: list[str] = Field(default_factory=list, max_length=1000)
    phone_numbers: list[str] = Field(default_factory=list, max_length=1000)
    blocked: bool

    @model_validator(mode="after")
    def require_targets(self):
        if not self.contact_ids and not self.phone_numbers:
            raise ValueError("Provide contact_ids or phone_numbers")
        return self


class BlockResult(BaseModel):
    updated: int
    blocked_total: int


class AdminConnectionRow(BaseModel):
    connection_id: str
    user_id: str
    user_email: str | None
    organization_id: str
    organization_name: str | None
    phone_number_id: str
    display_phone_number: str | None
    display_name: str
    status: str
    onboarding_type: str | None
    automation_enabled: bool
    contacts_total: int
    contacts_blocked: int
    contacts_synced_at: datetime | None
    last_message_at: datetime | None
    connected_at: datetime | None
    disconnected_at: datetime | None
    can_send_message: str | None


class AdminConnectionList(BaseModel):
    total: int
    connected: int
    automation_on: int
    items: list[AdminConnectionRow]
