"""Client-safe document snapshots and durable render jobs; no model-authored HTML or URLs."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, UniqueConstraint
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

DocumentKind = Literal["presentation", "comparison", "seller_evidence", "quotation"]


class DocumentField(BaseModel):
    label: str
    value: str


class DocumentMedia(BaseModel):
    id: str
    kind: Literal["image", "floor_plan"]
    caption: str


class DocumentProperty(BaseModel):
    reference: str
    title: str
    facts: list[DocumentField]
    evidence_date: str
    asking_price: str | None
    currency: str
    price_unit: str
    selling_points: list[str]
    trade_offs: list[str]
    missing_information: list[str]
    media: list[DocumentMedia] = Field(default_factory=list)


class DocumentSection(BaseModel):
    title: str
    rows: list[DocumentField]


class QuotationCharge(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    amount: Decimal | None = Field(
        default=None, ge=0, le=Decimal("1000000000"), max_digits=16, decimal_places=2
    )
    percent_of_asking: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=8, decimal_places=4
    )
    status: Literal["known", "estimate", "missing"]

    @model_validator(mode="after")
    def validate_amount(self):
        if self.status == "missing":
            if self.amount is not None or self.percent_of_asking is not None:
                raise ValueError("A missing charge cannot include an amount or percentage")
        elif (self.amount is None) == (self.percent_of_asking is None):
            raise ValueError(
                "Supply exactly one explicit amount or percentage for a known/estimated charge"
            )
        return self


class QuotationLine(BaseModel):
    label: str
    amount: str | None
    status: Literal["known", "estimate", "missing"]
    basis: str


class DocumentQuotation(BaseModel):
    currency: str
    lines: list[QuotationLine]
    known_total: str
    estimated_total: str
    total: str | None
    missing_charges: list[str]


class BrokerDocumentData(BaseModel):
    brand: str
    title: str
    reference: str
    version: int
    valid_until: date | None
    prepared_at: datetime
    properties: list[DocumentProperty]
    sections: list[DocumentSection] = Field(default_factory=list)
    quotation: DocumentQuotation | None = None
    limitations: list[str]


class BrokerDocumentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enquiry_id: int = Field(gt=0)
    scope: Literal["mine", "organization"] = "mine"
    kind: DocumentKind
    match_ids: list[int] = Field(
        min_length=1,
        max_length=6,
        description="Selected authorized property match IDs; never contact/owner IDs.",
    )
    reference: str = Field(min_length=1, max_length=80)
    version: int = Field(default=1, ge=1, le=9999)
    valid_until: date | None = None
    currency: Literal["AED"] = "AED"
    charges: list[QuotationCharge] = Field(
        default_factory=list,
        max_length=16,
        description="Only broker-explicit amounts or percentages. No default or invented fees; omitted charges remain unknown.",
    )
    missing_charges: list[str] = Field(
        default_factory=lambda: ["Other applicable charges not supplied"], max_length=16
    )
    media_ids: list[str] = Field(
        default_factory=list,
        max_length=12,
        description="Previously approved uploaded media IDs; remote URLs are never accepted.",
    )
    idempotency_key: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_kind(self):
        labels = [" ".join(charge.label.casefold().split()) for charge in self.charges]
        if len(labels) != len(set(labels)):
            raise ValueError(
                "Quotation charge labels must be distinct; do not count the same charge twice"
            )
        if len(set(self.match_ids)) != len(self.match_ids) or any(
            value <= 0 for value in self.match_ids
        ):
            raise ValueError("Select distinct positive match IDs")
        if self.kind == "quotation" and len(self.match_ids) != 1:
            raise ValueError(
                "A quotation must select exactly one property; alternatives are not additive"
            )
        if self.kind != "quotation" and (
            self.charges or self.missing_charges != ["Other applicable charges not supplied"]
        ):
            raise ValueError("Quotation charges apply only to quotations")
        if any(not value.strip() or len(value) > 120 for value in self.missing_charges):
            raise ValueError("Missing charge labels must contain 1–120 characters")
        return self


class BrokerDocumentGet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=36, max_length=36)


class BrokerDocumentResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    kind: DocumentKind
    title: str
    version: int
    document: BrokerDocumentData
    error: str | None = None
    created_at: datetime
    download_url: str | None = None


class CrmBrokerDocument(SQLModel, table=True):
    __tablename__ = "crm_broker_documents"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", "idempotency_key", name="uq_broker_document_request"
        ),
    )
    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str = SQLField(index=True)
    enquiry_id: int = SQLField(foreign_key="crm_inbound_enquiries.id", index=True)
    scope: str = "mine"
    kind: str
    status: str = SQLField(default="queued", index=True)
    idempotency_key: str
    input_hash: str
    document_json: dict = SQLField(sa_column=Column(JSON, nullable=False))
    attempt_count: int = 0
    lease_until: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))
    claim_token: str | None = None
    object_key: str | None = None
    sha256: str | None = None
    error: str | None = None
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmBrokerMedia(SQLModel, table=True):
    __tablename__ = "crm_broker_media"
    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str
    enquiry_id: int = SQLField(foreign_key="crm_inbound_enquiries.id", index=True)
    match_id: int = SQLField(foreign_key="crm_inbound_matches.id", index=True)
    kind: str
    object_key: str
    sha256: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
