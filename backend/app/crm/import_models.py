from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

CrmContactImportStatus = Literal["queued", "processing", "retry_wait", "completed", "failed"]
CrmOwnershipStatus = Literal[
    "verified_current_owner",
    "probable_current_owner",
    "unit_linked_unverified",
    "former_owner",
    "unverified_former_owner",
    "conflicting_claim",
    "insufficient_property_data",
    "registry_not_observed",
    "unmatched",
]


# JSONB on PostgreSQL, plain JSON where the unit tests create tables in SQLite
_JSONB = JSON().with_variant(JSONB(), "postgresql")


class CrmContactImport(SQLModel, table=True):
    __tablename__ = "crm_contact_imports"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "sha256",
            name="uq_crm_contact_import_organization_hash",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    created_by_user_id: str = SQLField(index=True)
    name: str
    original_filename: str
    sha256: str = SQLField(index=True)
    size_bytes: int
    status: str = SQLField(default="processing", index=True)
    mapping: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    owner_source_metadata: dict[str, Any] = SQLField(
        default_factory=dict,
        exclude=True,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'{}'")
        ),
    )
    summary: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    error_message: str | None = SQLField(default=None, sa_column=Column(Text))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: datetime | None = SQLField(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class CrmOwnerAssessmentRevision(SQLModel, table=True):
    """Transactionally visible, non-reused source token for one tenant."""

    __tablename__ = "crm_owner_assessment_revisions"

    organization_id: str = SQLField(primary_key=True)
    revision: int = SQLField(sa_type=BigInteger)


class CrmOwnerAssessmentState(SQLModel, table=True):
    """Which stored assessment generation is current for a tenant, and what it was built from."""

    __tablename__ = "crm_owner_assessment_state"

    organization_id: str = SQLField(primary_key=True)
    generation: int = SQLField(sa_type=BigInteger)
    revision: str
    warehouse_revision: str
    checked_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    warehouse_status: str
    built_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    summary: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))
    import_summaries: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))
    list_counts: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))
    source_audit: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))


class CrmOwnerAssessedClaim(SQLModel, table=True):
    """One claim's assessed row for one generation; see ``app.crm.owner_store``."""

    __tablename__ = "crm_owner_assessed_claims"
    __table_args__ = (
        Index(
            "ix_crm_assessed_claim_canonical",
            "organization_id",
            "generation",
            "canonical_owner_key",
        ),
        Index("ix_crm_assessed_claim_owner", "organization_id", "generation", "owner_key"),
        Index("ix_crm_assessed_claim_list", "organization_id", "generation", "list_id", "ord"),
        Index("ix_crm_assessed_claim_import", "organization_id", "generation", "import_id", "ord"),
        Index(
            "ix_crm_assessed_claim_identity",
            "organization_id",
            "generation",
            "identity_key",
            "identity_area",
        ),
        Index("ix_crm_assessed_claim_property", "organization_id", "generation", "property_key"),
    )

    organization_id: str = SQLField(primary_key=True)
    generation: int = SQLField(sa_column=Column(BigInteger, primary_key=True))
    claim_id: int = SQLField(primary_key=True)
    list_id: int
    import_id: int
    owner_key: str
    canonical_owner_key: str
    property_key: str
    identity_area: str | None = None
    identity_key: str | None = None
    group_ident: str
    is_source: bool
    ord: int = SQLField(sa_type=BigInteger)
    assessed_status: str
    party_role: str
    transaction_date: date | None = None
    event_conf: int
    pref_support: bool
    pref_buyer: bool
    ready_row: bool
    lead_id: str | None = None
    building_name: str | None = None
    project_name: str | None = None
    unit_number: str | None = None
    area_name: str | None = None
    match_colour: str | None = None
    match_outcome: str | None = None
    search_text: str = SQLField(sa_column=Column(Text, nullable=False))
    props_search_text: str = SQLField(sa_column=Column(Text, nullable=False))
    row: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))


class CrmOwnerRegistryOwner(SQLModel, table=True):
    """One owner's profile in one generation; ``list_id`` 0 is the whole tenant."""

    __tablename__ = "crm_owner_registry_owners"
    __table_args__ = (
        Index("ix_crm_registry_owner_key", "organization_id", "generation", "list_id", "owner_key"),
    )

    organization_id: str = SQLField(primary_key=True)
    generation: int = SQLField(sa_column=Column(BigInteger, primary_key=True))
    list_id: int = SQLField(primary_key=True)
    canonical_owner_key: str = SQLField(primary_key=True)
    owner_key: str
    profile: dict[str, Any] = SQLField(sa_column=Column(_JSONB, nullable=False))
    search_text: str = SQLField(sa_column=Column(Text, nullable=False))
    property_count: int
    contact_ready_count: int
    highest_confidence_score: int
    next_lease_end: date | None = None
    developer_side_seller: bool
    invalid_identity_sources: bool
    no_properties: bool
    in_rental: bool
    in_registry: bool
    in_prior: bool
    in_review: bool
    in_multi: bool


class CrmOwnerRegistryProperty(SQLModel, table=True):
    """What the registry filters on for one property of an owner's profile."""

    __tablename__ = "crm_owner_registry_properties"

    organization_id: str = SQLField(primary_key=True)
    generation: int = SQLField(sa_column=Column(BigInteger, primary_key=True))
    list_id: int = SQLField(primary_key=True)
    canonical_owner_key: str = SQLField(primary_key=True)
    ordinal: int = SQLField(primary_key=True)
    status: str
    ready: bool
    rental_linked: bool
    lease_end: date | None = None
    annual_rent_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    sale_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    match_status: str | None = None
    location_text: str = SQLField(sa_column=Column(Text, nullable=False))
    headline_rank: int
    confidence: int


class CrmContactList(SQLModel, table=True):
    __tablename__ = "crm_contact_lists"

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    created_by_user_id: str = SQLField(index=True)
    source_import_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            ForeignKey("crm_contact_imports.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    name: str
    description: str | None = SQLField(default=None, sa_column=Column(Text))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmPropertyContactClaim(SQLModel, table=True):
    __tablename__ = "crm_property_contact_claims"
    # Indexes and BIGINT amounts mirror the migrations, which are the schema authority; tests
    # compare this model with a freshly migrated database. The ranking indexes of d9f4b6c8e3a2
    # were dropped by b6d2f8a4c1e7: no query could use them.
    __table_args__ = (
        UniqueConstraint(
            "import_id",
            "source_sheet",
            "source_row_number",
            name="uq_crm_property_contact_claim_source_row",
        ),
        Index("ix_crm_claim_org_owner", "organization_id", "owner_key"),
        Index("ix_crm_claim_org_property", "organization_id", "property_key"),
        Index("ix_crm_claim_org_owner_property", "organization_id", "owner_key", "property_key"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    import_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_contact_imports.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    list_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_contact_lists.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    source_sheet: str
    source_row_number: int
    row_fingerprint: str = SQLField(index=True)
    owner_key: str
    property_key: str
    contact_name: str
    phone_primary: str | None = None
    phone_alternate: str | None = None
    email_primary: str | None = None
    area_name: str = ""
    project_name: str = ""
    building_name: str = ""
    unit_number: str = ""
    property_type: str = ""
    transaction_date: date | None = None
    transaction_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    party_role: str = ""
    procedure_type: str = ""
    ownership_status: str = SQLField(index=True)
    confidence_score: int = 0
    match_reason: str = SQLField(sa_column=Column(Text, nullable=False))
    lead_id: str | None = SQLField(default=None, index=True)
    unit_candidate_key: str | None = SQLField(default=None, index=True)
    latest_sale_date: date | None = None
    latest_sale_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    later_sale_date: date | None = None
    lease_end: date | None = None
    annual_rent_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    evidence: dict[str, Any] = SQLField(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    owner_history_evidence: dict[str, Any] = SQLField(
        default_factory=dict,
        exclude=True,
        sa_column=Column(
            JSON().with_variant(JSONB(), "postgresql"), nullable=False, server_default=text("'{}'")
        ),
    )
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmSourcePropertyCounts(BaseModel):
    """File inventory before owner filtering; identifiers are not verified properties."""

    total_rows: int = 0
    distinct_unit_numbers: int = 0
    distinct_building_numbers_without_unit: int = 0
    distinct_identifiers: int = 0
    distinct_property_numbers_without_unit: int = 0
    source_property_references: int = 0
    identifiers_in_both_columns: int = 0
    location_scoped_units: int = 0
    unit_rows: int = 0
    building_fallback_rows: int = 0
    rows_without_identifiers: int = 0
    unit_rows_without_location: int = 0


class CrmSourceAuditSummary(BaseModel):
    mode: Literal["source_only", "source_transaction_matched"] = "source_only"
    matched_reference_count: int = 0
    matched_registry_property_count: int = 0
    unmatched_reference_count: int = 0
    ambiguous_reference_count: int = 0
    excluded_match_reference_count: int = 0
    current_owner_association_count: int = 0
    former_owner_association_count: int = 0
    import_count: int = 0
    reference_count: int = 0
    owner_candidate_reference_count: int = 0
    bank_reference_count: int = 0
    excluded_nonownership_reference_count: int = 0
    review_reference_count: int = 0
    excluded_scope_reference_count: int = 0
    source_row_count: int = 0
    disposition_counts: dict[str, int] = Field(default_factory=dict)


CrmMatchColour = Literal["green", "amber", "blue", "red", "grey"]


class CrmOwnerMatchUnits(BaseModel):
    """Distinct units (building or project label + identifier keys) by their best row's tier."""

    model_config = ConfigDict(json_schema_mode_override="serialization")

    total: int
    confirmed: int  # green
    review: int  # amber
    property_only: int  # blue
    not_matched: int  # red or grey


class CrmOwnerMatchSales(BaseModel):
    """Distinct sales that confirmed rows are tied to, by where the sale came from."""

    model_config = ConfigDict(json_schema_mode_override="serialization")

    transactions: int = 0  # found in the Transactions data
    registry: int = 0  # a sale event of the property registry
    total: int = 0


class CrmOwnerMatchSummary(BaseModel):
    """What the property-first matcher made of an import's rows."""

    # One schema for request and response: a nested model otherwise makes FastAPI split the
    # whole import summary into -Input and -Output copies, which renames the generated types.
    model_config = ConfigDict(json_schema_mode_override="serialization")

    version: str
    rows: dict[str, int]  # outcome -> rows
    units: CrmOwnerMatchUnits
    rows_without_unit: int
    # Rows in review (amber) by their one primary reason: unit_differs, two_units_named,
    # share_differs, size_differs, unit_unverified, type_differs, other. Only non-zero keys.
    review_reasons: dict[str, int] = Field(default_factory=dict)
    sales_matched: CrmOwnerMatchSales = Field(default_factory=CrmOwnerMatchSales)


class CrmContactImportSummary(BaseModel):
    owner_match: CrmOwnerMatchSummary | None = None
    source_audit: CrmSourceAuditSummary | None = None
    total_rows: int = 0
    candidate_rows: int = 0
    # Distinct properties (building + unit) among the kept rows: one unit sold several times,
    # with a buyer and a seller row per sale, counts once. None for imports made before it.
    distinct_properties: int | None = None
    source_property_counts: CrmSourcePropertyCounts | None = None
    rows_with_sales_history: int | None = None
    properties_linked_rows: int | None = None
    plot_only_rows: int | None = None
    duplicate_rows_collapsed: int = 0
    dropped_no_unit: int = 0
    valid_contacts: int = 0
    verified_current_owners: int = 0
    probable_current_owners: int = 0
    unit_linked_unverified: int = 0
    former_owners: int = 0
    unverified_former_owners: int = 0
    conflicting_claims: int = 0
    insufficient_property_data: int = 0
    registry_not_observed: int = 0
    unmatched: int = 0
    rental_opportunities: int = 0
    contact_ready: int = 0
    # Rows not kept, per reason (see CrmDroppedRowReason); dropped_log says whether the
    # dropped-rows log was saved, so imports from before it existed can say so.
    dropped_by_reason: dict[str, int] = Field(default_factory=dict)
    dropped_log: bool = False


CrmDroppedRowReason = Literal["no_name", "not_buyer_seller", "not_a_sale", "no_unit"]


class CrmDroppedRow(BaseModel):
    """A row the import did not keep, with the file's own values and why it was dropped."""

    sheet: str
    row: int
    reason: CrmDroppedRowReason
    name: str = ""
    building: str = ""
    unit: str = ""
    date: str = ""
    price: str = ""
    role: str = ""
    procedure: str = ""


class CrmDroppedRowsResponse(BaseModel):
    available: bool
    total: int
    offset: int
    limit: int
    by_reason: dict[str, int]
    rows: list[CrmDroppedRow]


class CrmImportPropertyRecord(BaseModel):
    """One retained source event; sale_date is the legacy API name for its date."""

    name: str
    role: str
    sale_date: date | None = None
    price_aed: int | None = None
    status: str
    sheet: str
    row: int
    procedure: str = ""
    event_family: str = ""
    identifiers: dict[str, str] = Field(default_factory=dict)
    match_reason: str = ""
    property_details: dict[str, str] = Field(default_factory=dict)


class CrmImportProperty(BaseModel):
    """One distinct property (building + unit) of an import, with its kept rows."""

    property_key: str
    area: str
    project: str
    building: str
    unit: str
    property_type: str
    rows: int
    buyers: int
    sellers: int
    # Name on the strongest verified/probable current-owner row; None when there is none.
    current_owner: str | None = None
    latest_date: date | None = None
    latest_price_aed: int | None = None
    records: list[CrmImportPropertyRecord]
    records_truncated: bool = False


class CrmImportPropertiesResponse(BaseModel):
    total: int
    offset: int
    limit: int
    rows: list[CrmImportProperty]


class CrmSheetMapping(BaseModel):
    sheet_name: str
    header_row: int
    meaningful_rows: int
    sheet_family: str
    mapping_source: Literal["heuristic", "llm", "reused", "override", "heuristic_fallback"]
    confidence: float = Field(ge=0, le=1)
    field_map: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CrmPreviewColumn(BaseModel):
    header: str
    # The field this column feeds; None when the import will not read it.
    field: str | None = None


class CrmSheetPreview(BaseModel):
    sheet_name: str
    rows: int
    columns: list[CrmPreviewColumn] = Field(default_factory=list)
    # Some data columns still have no role; the model assigns them when the file is imported.
    mapped_at_import: bool = False


class CrmContactImportPreview(BaseModel):
    sheets: list[CrmSheetPreview] = Field(default_factory=list)


class CrmContactImportResponse(BaseModel):
    id: int
    list_id: int | None = None
    name: str
    original_filename: str
    status: CrmContactImportStatus
    summary: CrmContactImportSummary
    mappings: list[CrmSheetMapping] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class CrmContactImportRename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CrmContactListSummary(BaseModel):
    id: int
    source_import_id: int | None = None
    name: str
    description: str | None = None
    total_contacts: int = 0
    contact_ready: int = 0
    needs_review: int = 0
    former_owners: int = 0
    created_at: datetime
    updated_at: datetime


class CrmMatchedSale(BaseModel):
    """The sale a row was matched to: a DXBI event or a Transactions (DLD) row."""

    unit: str = ""
    building: str = ""
    project: str = ""
    area: str = ""
    amount_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    date: str = ""
    sqft: float | None = None
    source: str = ""


class CrmContactClaimResponse(BaseModel):
    id: int
    source_sheet: str
    source_row_number: int
    contact_name: str
    phone_primary: str | None = None
    phone_alternate: str | None = None
    email_primary: str | None = None
    area_name: str
    project_name: str
    building_name: str
    unit_number: str
    property_type: str
    property_details: dict[str, str] = Field(default_factory=dict)
    transaction_date: date | None = None
    transaction_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    ownership_status: CrmOwnershipStatus
    confidence_score: int
    match_reason: str
    lead_id: str | None = None
    unit_candidate_key: str | None = None
    latest_sale_date: date | None = None
    latest_sale_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    later_sale_date: date | None = None
    lease_end: date | None = None
    annual_rent_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    owner_key: str
    duplicate_count: int = 1
    source_rows: list[str] = Field(default_factory=list)
    match_outcome: str | None = None
    match_colour: CrmMatchColour | None = None
    match_reasons: list[str] = Field(default_factory=list)
    match_warnings: list[str] = Field(default_factory=list)
    matched_sale: CrmMatchedSale | None = None


class CrmContactListDetail(BaseModel):
    list: CrmContactListSummary
    contacts: list[CrmContactClaimResponse]
    total: int
    limit: int
    offset: int


class CrmLeadImportedContact(BaseModel):
    claim_id: int
    list_id: int
    list_name: str
    contact_name: str
    phone_primary: str | None = None
    phone_alternate: str | None = None
    email_primary: str | None = None
    ownership_status: CrmOwnershipStatus
    confidence_score: int
    match_reason: str
    source_sheet: str
    imported_at: datetime
    owner_key: str
    duplicate_count: int = 1
    property_count: int = 1
    source_lists: list[str] = Field(default_factory=list)


class CrmOwnerSourceReference(BaseModel):
    transaction_match_status: Literal["matched", "unmatched", "ambiguous", "excluded"] | None = None
    ownership_evidence_basis: Literal["transaction_supported", "workbook_only"] | None = None
    reference_id: str
    kind: str
    source_key: list[str]
    building_number: str = ""
    land_number: str = ""
    dm_sub_number: str = ""
    size_sqm: str | None = None
    disposition: str


class CrmOwnerProperty(BaseModel):
    source_reference: CrmOwnerSourceReference | None = None
    property_key: str
    area_name: str
    project_name: str
    building_name: str
    unit_number: str
    property_type: str
    ownership_status: CrmOwnershipStatus
    confidence_score: int
    match_reason: str
    lead_id: str | None = None
    unit_candidate_key: str | None = None
    imported_transaction_date: date | None = None
    imported_transaction_price_aed: int | None = None
    imported_property_type: str = ""
    imported_party_role: str = ""
    latest_sale_date: date | None = None
    latest_sale_price_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    registry_sale_date: date | None = None
    registry_sale_price_aed: int | None = None
    registry_property_type: str | None = None
    registry_bedrooms: str | None = None
    registry_size_sqft: float | None = None
    registry_built_up_area_sqft: float | None = None
    registry_price_per_sqft_aed: float | None = None
    registry_market_status: str | None = None
    registry_unit_number: str | None = None
    registry_building_name: str | None = None
    registry_area_name: str | None = None
    later_sale_date: date | None = None
    lease_end: date | None = None
    annual_rent_aed: int | None = SQLField(default=None, sa_type=BigInteger)
    duplicate_count: int = 1
    source_lists: list[str] = Field(default_factory=list)
    source_rows: list[str] = Field(default_factory=list)


class CrmOwnerHistorySummary(BaseModel):
    """Source rows and evidence associations, not a legal ownership guarantee."""

    source_event_count: int
    identifiable_property_count: int
    owner_property_count: int
    verified_current_count: int
    probable_current_count: int
    former_count: int
    unresolved_count: int
    invalid_identity_source_count: int
    legacy_source_event_count: int
    resolver_versions: dict[str, int]
    unverified_former_count: int = 0
    checked_at: datetime | None = None
    warehouse_status: Literal["available", "unavailable", "not_requested"] = "unavailable"
    assessment_version: str = ""


class CrmOwnerHistoryEvent(BaseModel):
    id: int
    import_id: int
    source_filename: str
    source_sheet: str
    source_row_number: int
    contact_name: str
    property_key: str | None = None
    area_name: str
    project_name: str
    building_name: str
    unit_number: str
    property_type: str
    party_role: str
    procedure_type: str
    event_family: str
    transaction_date: date | None = None
    transaction_price_aed: int | None = None
    observed_ownership_status: CrmOwnershipStatus
    current_ownership_status: CrmOwnershipStatus
    confidence_score: int
    evidence_reason: str
    current_evidence_reason: str
    resolver_version: str | None = None


class CrmOwnerHistoryResponse(BaseModel):
    owner_key: str
    summary: CrmOwnerHistorySummary
    events: list[CrmOwnerHistoryEvent]
    total: int
    limit: int
    offset: int


class CrmOwnerProfile(BaseModel):
    phone_numbers: list[str] = Field(default_factory=list)
    owner_key: str
    contact_name: str
    phone_primary: str | None = None
    phone_alternate: str | None = None
    email_primary: str | None = None
    highest_ownership_status: CrmOwnershipStatus
    highest_confidence_score: int
    property_count: int
    rental_linked_count: int
    contact_ready_count: int
    annual_rent_aed: int
    next_lease_end: date | None = None
    properties: list[CrmOwnerProperty] = Field(default_factory=list)
    history_summary: CrmOwnerHistorySummary | None = None
    relationship_role: Literal["unknown", "possible_intermediary", "organization"] = "unknown"
    role_signals: list[str] = Field(default_factory=list)
    # A developer, or a person selling for one; never listed among former owners.
    developer_side_seller: bool = False
    # Properties held now (verified or probable current owner).
    current_property_count: int = 0
    # Every associated property, when the list counts only those in its view.
    total_property_count: int | None = None


class CrmOwnerRegistrySummary(BaseModel):
    rental_owner_profiles: int = 0
    registry_owner_profiles: int = 0
    prior_owner_profiles: int = 0
    needs_review_profiles: int = 0
    multi_property_owners: int = 0


class CrmOwnerRegistryResponse(BaseModel):
    source_audit: CrmSourceAuditSummary | None = None
    scope: Literal[
        "all", "current_owners", "rental_ready", "registry", "prior_owners", "needs_review"
    ]
    owners: list[CrmOwnerProfile]
    total: int
    limit: int
    offset: int
    summary: CrmOwnerRegistrySummary


class CrmOwnerWorkspace(SQLModel, table=True):
    __tablename__ = "crm_owner_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "organization_id",
            "owner_key",
            name="uq_crm_owner_workspace_identity",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    owner_key: str = SQLField(index=True)
    pipeline_status: str = SQLField(default="new", index=True)
    highlight_color: str = SQLField(default="none")
    next_follow_up: date | None = None
    tags: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmOwnerNote(SQLModel, table=True):
    __tablename__ = "crm_owner_notes"

    id: int | None = SQLField(default=None, primary_key=True)
    workspace_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_owner_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    body: str = SQLField(sa_column=Column(Text, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmOwnerWorkspaceSummary(BaseModel):
    owner_key: str
    pipeline_status: Literal[
        "new",
        "researching",
        "contact_ready",
        "contacted",
        "qualified",
        "nurture",
        "won",
        "closed",
    ]
    highlight_color: Literal["none", "amber", "green", "blue", "red", "purple"]
    next_follow_up: date | None = None
    tags: list[str] = Field(default_factory=list)
    note_count: int = 0
    last_note: str | None = None
    updated_at: datetime


class CrmOwnerBulkUpdate(BaseModel):
    owner_keys: list[str] = Field(min_length=1, max_length=200)
    pipeline_status: (
        Literal[
            "new",
            "researching",
            "contact_ready",
            "contacted",
            "qualified",
            "nurture",
            "won",
            "closed",
        ]
        | None
    ) = None
    highlight_color: Literal["none", "amber", "green", "blue", "red", "purple"] | None = None
    note: str | None = Field(default=None, max_length=4_000)
