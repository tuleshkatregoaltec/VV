from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

InboundIntent = Literal["buy", "rent", "sell", "let"]
InboundStatus = Literal[
    "new",
    "needs_review",
    "assigned",
    "contacted",
    "qualified",
    "active",
    "won",
    "nurture",
    "closed_lost",
]
InboundMatchState = Literal["suggested", "saved", "dismissed", "contacted"]


class CrmInboundImport(SQLModel, table=True):
    __tablename__ = "crm_inbound_imports"
    __table_args__ = (
        UniqueConstraint("organization_id", "sha256", name="uq_crm_inbound_import_org_hash"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    created_by_user_id: str = SQLField(index=True)
    name: str
    original_filename: str
    sha256: str = SQLField(index=True)
    size_bytes: int
    status: str = SQLField(default="processing", index=True)
    mapping: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    summary: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    error_message: str | None = SQLField(default=None, sa_column=Column(Text))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class CrmInboundContact(SQLModel, table=True):
    __tablename__ = "crm_inbound_contacts"

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    full_name: str
    phone: str | None = SQLField(default=None, index=True)
    email: str | None = SQLField(default=None, index=True)
    whatsapp: str | None = None
    preferred_language: str | None = None
    preferred_channel: str | None = None
    consent_status: str = SQLField(default="unknown", index=True)
    do_not_contact: bool = SQLField(default=False, index=True)
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmInboundEnquiry(SQLModel, table=True):
    __tablename__ = "crm_inbound_enquiries"

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    contact_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_inbound_contacts.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    source_import_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            ForeignKey("crm_inbound_imports.id", ondelete="SET NULL"), nullable=True, index=True
        ),
    )
    created_by_user_id: str = SQLField(index=True)
    assigned_user_id: str | None = SQLField(default=None, index=True)
    intent: str = SQLField(index=True)
    status: str = SQLField(default="new", index=True)
    source: str = SQLField(default="Manual", index=True)
    campaign: str | None = SQLField(default=None, index=True)
    source_lead_id: str | None = SQLField(default=None, index=True)
    source_sheet: str | None = None
    source_row_number: int | None = None
    enquiry_date: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    criteria: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    strict_fields: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    raw_notes: str | None = SQLField(default=None, sa_column=Column(Text))
    extraction_confidence: float = 1.0
    extraction_evidence: dict[str, Any] = SQLField(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    review_reasons: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    next_follow_up: date | None = None
    tags: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmInboundNote(SQLModel, table=True):
    __tablename__ = "crm_inbound_notes"

    id: int | None = SQLField(default=None, primary_key=True)
    enquiry_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_inbound_enquiries.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    organization_id: str = SQLField(index=True)
    user_id: str = SQLField(index=True)
    body: str = SQLField(sa_column=Column(Text, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmInboundMatch(SQLModel, table=True):
    __tablename__ = "crm_inbound_matches"
    __table_args__ = (
        UniqueConstraint(
            "enquiry_id", "target_type", "target_key", name="uq_crm_inbound_match_target"
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    enquiry_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_inbound_enquiries.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    organization_id: str = SQLField(index=True)
    target_type: str = SQLField(index=True)
    target_key: str = SQLField(index=True)
    score: int = SQLField(index=True)
    state: str = SQLField(default="suggested", index=True)
    title: str
    subtitle: str
    reasons: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    score_breakdown: dict[str, Any] = SQLField(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    snapshot: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    algorithm_version: str = "inbound-v1"
    generated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class InboundImportSummary(BaseModel):
    total_rows: int = 0
    imported: int = 0
    duplicates: int = 0
    needs_review: int = 0
    buyers: int = 0
    tenants: int = 0
    sellers: int = 0
    landlords: int = 0


class InboundImportResponse(BaseModel):
    id: int
    name: str
    original_filename: str
    status: Literal["processing", "completed", "failed"]
    summary: InboundImportSummary
    mapping: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class InboundContactResponse(BaseModel):
    id: int
    full_name: str
    phone: str | None = None
    email: str | None = None
    whatsapp: str | None = None
    preferred_language: str | None = None
    preferred_channel: str | None = None
    consent_status: str
    do_not_contact: bool


class InboundEnquiryCreate(BaseModel):
    intent: InboundIntent
    full_name: str = Field(min_length=1, max_length=240)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=320)
    whatsapp: str | None = Field(default=None, max_length=80)
    source: str = Field(default="Manual", max_length=120)
    campaign: str | None = Field(default=None, max_length=200)
    assigned_user_id: str | None = None
    notes: str | None = Field(default=None, max_length=8_000)
    criteria: dict[str, Any] = Field(default_factory=dict)
    strict_fields: list[str] = Field(default_factory=list, max_length=20)
    consent_status: str = "unknown"


class InboundEnquiryUpdate(BaseModel):
    intent: InboundIntent | None = None
    status: InboundStatus | None = None
    assigned_user_id: str | None = None
    criteria: dict[str, Any] | None = None
    strict_fields: list[str] | None = Field(default=None, max_length=20)
    next_follow_up: date | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=8_000)


class InboundNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4_000)


class InboundNoteResponse(BaseModel):
    id: int
    body: str
    user_id: str
    created_at: datetime


class InboundEnquiryResponse(BaseModel):
    id: int
    contact: InboundContactResponse
    intent: InboundIntent
    status: InboundStatus
    assigned_user_id: str | None = None
    source: str
    campaign: str | None = None
    source_import_id: int | None = None
    enquiry_date: datetime
    criteria: dict[str, Any]
    strict_fields: list[str]
    raw_notes: str | None = None
    extraction_confidence: float
    review_reasons: list[str]
    next_follow_up: date | None = None
    tags: list[str]
    notes: list[InboundNoteResponse] = Field(default_factory=list)
    match_count: int = 0
    saved_match_count: int = 0
    created_at: datetime
    updated_at: datetime


class InboundEnquiryListResponse(BaseModel):
    enquiries: list[InboundEnquiryResponse]
    total: int
    summary: dict[str, int]


class InboundMatchResponse(BaseModel):
    id: int
    target_type: Literal["owner", "unit", "listing", "demand"]
    target_key: str
    score: int
    state: InboundMatchState
    title: str
    subtitle: str
    reasons: list[str]
    score_breakdown: dict[str, Any]
    snapshot: dict[str, Any]
    generated_at: datetime


class InboundMatchesResponse(BaseModel):
    enquiry_id: int
    listing_fresh: bool
    listing_last_refresh: datetime | None = None
    lanes: dict[str, list[InboundMatchResponse]]


class InboundMatchUpdate(BaseModel):
    state: InboundMatchState
