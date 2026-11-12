"""Listing documents: private information an agent saves for a listing, and the PDFs made from it.

Owner and agreement details are private to the organization; they never go to the shared
ClickHouse inventory. A generated document keeps the exact input it was made from.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import CheckConstraint, DateTime, Index, UniqueConstraint
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

from app.crm.models import CrmCompanyListingDetail

DocType = Literal["noc", "brochure", "lease", "a2a"]
DocStatus = Literal["generating", "ready", "failed"]
Source = Literal["property_finder"]
DOC_TYPES: tuple[str, ...] = ("noc", "brochure", "lease", "a2a")
DOC_STATUSES: tuple[str, ...] = ("generating", "ready", "failed")
# Property Finder listing ids: 26 letters and digits today; bounded, no separators.
LISTING_KEY_PATTERN = r"^[A-Za-z0-9]{1,40}$"

ListingKey = Annotated[str, StringConstraints(pattern=LISTING_KEY_PATTERN)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OwnerFields(_Group):
    full_name: Text | None = None
    phone: Text | None = None
    email: EmailStr | None = None
    title_deed_number: Text | None = None
    id_number: Text | None = None


class LeaseFields(_Group):
    tenant_name: Text | None = None
    tenant_phone: Text | None = None
    tenant_email: EmailStr | None = None
    start_date: date | None = None
    end_date: date | None = None
    annual_rent_aed: int | None = Field(default=None, ge=0)
    cheques: int | None = Field(default=None, ge=1, le=12)
    security_deposit_aed: int | None = Field(default=None, ge=0)


class A2AFields(_Group):
    other_brokerage: Text | None = None
    other_broker_name: Text | None = None
    other_broker_brn: Text | None = None
    commission_split_pct: Decimal | None = Field(default=None, ge=0, le=100)
    valid_until: date | None = None


class MarketingFields(_Group):
    description: LongText | None = None


class DocumentFields(_Group):
    """Everything the Documents tab collects for one listing (all optional until a template needs it)."""

    owner: OwnerFields = Field(default_factory=OwnerFields)
    lease: LeaseFields = Field(default_factory=LeaseFields)
    a2a: A2AFields = Field(default_factory=A2AFields)
    marketing: MarketingFields = Field(default_factory=MarketingFields)


class CrmListingDocumentInfo(SQLModel, table=True):
    """The saved document information for one listing, per organization."""

    __tablename__ = "crm_listing_document_info"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "source", "listing_key", name="uq_crm_listing_document_info_source"
        ),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    organization_id: str = SQLField(foreign_key="organizations.id", ondelete="CASCADE", index=True)
    source: str
    listing_key: str
    listing_title: str
    fields: dict[str, Any] = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    revision: int = 1
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmGeneratedDocument(SQLModel, table=True):
    """One generated PDF and the input snapshot it was made from; never rewritten by later edits."""

    __tablename__ = "crm_generated_documents"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_crm_generated_document_idempotency"
        ),
        CheckConstraint(
            "doc_type IN ('noc', 'brochure', 'lease', 'a2a')", name="ck_crm_generated_document_type"
        ),
        CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_crm_generated_document_status"
        ),
        Index(
            "ix_crm_generated_documents_listing",
            "organization_id",
            "source",
            "listing_key",
            "created_at",
        ),
    )

    id: UUID = SQLField(default_factory=uuid4, primary_key=True)
    organization_id: str = SQLField(foreign_key="organizations.id", ondelete="CASCADE", index=True)
    info_id: UUID = SQLField(foreign_key="crm_listing_document_info.id", ondelete="CASCADE")
    source: str
    listing_key: str
    listing_title: str
    doc_type: str
    template_version: str
    snapshot: dict[str, Any] = SQLField(
        default_factory=dict, sa_column=Column(JSON, nullable=False)
    )
    input_revision: int
    idempotency_key: UUID
    status: str
    object_key: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    failure_code: str | None = None
    created_by_user_id: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class ListingDocumentInfoResponse(BaseModel):
    listing: CrmCompanyListingDetail
    fields: DocumentFields
    # 0 = nothing saved yet.
    revision: int


class ListingDocumentInfoUpdate(_Group):
    source: Source
    listing_key: ListingKey
    fields: DocumentFields
    expected_revision: int = Field(ge=0)


class GenerateDocumentRequest(_Group):
    source: Source
    listing_key: ListingKey
    doc_type: DocType
    expected_revision: int = Field(ge=1)
    idempotency_key: UUID


class GeneratedDocumentResponse(BaseModel):
    """What the lists show; never the private snapshot or the storage key."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    listing_key: str
    listing_title: str
    company_name: str | None = None
    listing_area: str | None = None
    doc_type: DocType
    template_version: str
    status: DocStatus
    failure_code: str | None
    size_bytes: int | None
    created_by_user_id: str
    created_at: datetime


class GeneratedDocumentListResponse(BaseModel):
    items: list[GeneratedDocumentResponse]
    total: int
    limit: int
    offset: int


class DocumentDownloadResponse(BaseModel):
    url: str
    expires_at: datetime
