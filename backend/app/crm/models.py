from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

# ClickHouse Date's zero value, which a left join gives a lease with no matched sale.
_ZERO_DATE = date(1970, 1, 1)

LeadStatus = Literal["expired", "expiring_30", "expiring_60", "expiring_90"]
LeadPriority = Literal["urgent", "high", "medium"]
MatchConfidence = Literal["high", "medium", "low"]
CrmAssetClass = Literal["residential", "commercial", "other"]
CrmPipelineStatus = Literal[
    "new",
    "researching",
    "contact_ready",
    "contacted",
    "qualified",
    "nurture",
    "won",
    "closed",
]
CrmHighlightColor = Literal["none", "amber", "green", "blue", "red", "purple"]


class CrmLead(BaseModel):
    lead_id: str
    unit_candidate_key: str
    building_name: str
    project_name: str
    area_name: str
    registry_building_name: str = ""
    registry_project_name: str = ""
    registry_area_name: str = ""
    canonical_location_id: str | None = None
    geography_match_status: str = "unmapped"
    coordinate_precision: str = "missing"
    latitude: float | None = None
    longitude: float | None = None
    asset_class: CrmAssetClass = "other"
    property_type: str
    property_subtype: str = "Property"
    matched_sales_property_type: str | None = None
    bedrooms: str
    size_sqft: float | None = None
    contract_amount_aed: int = 0
    contract_term_days: int = 0
    contract_term_months: float | None = None
    annual_rent_aed: int
    latest_purchase_price_aed: int | None = None
    unit_number: str | None = None
    unit_match_status: str = "unresolved"
    matching_units: int = 0
    last_purchase_date: date | None = None
    matched_sale_price_aed: int | None = None
    gross_yield_pct: float | None = None
    identity_sale_date: date | None = None
    identity_sale_price_aed: int | None = None
    latest_price_per_sqft_aed: float | None = None
    latest_capital_gain_pct: float | None = None
    latest_ltv_pct: float | None = None
    latest_seller_type: str | None = None
    latest_seller_transaction_count: int | None = None
    latest_market_status: str | None = None
    lease_start: date
    lease_end: date
    days_to_expiry: int
    status: LeadStatus
    priority: LeadPriority
    score: int = Field(ge=0, le=100)
    contract_state: str
    match_confidence: MatchConfidence
    property_identity_key: str = ""
    ownership_timing: str = "unit_unresolved"
    lease_evidence_state: str = "upcoming"
    data_complete_through: date | None = None
    lead_reason: str
    recommended_action: str
    sale_conversation: bool
    source: str = "Transaction registry"

    @field_validator("last_purchase_date", "identity_sale_date", mode="before")
    @classmethod
    def _no_zero_date(cls, value: Any) -> Any:
        """A lease without a matched sale reads Date's zero value (1970-01-01): no date."""
        if value in (_ZERO_DATE, _ZERO_DATE.isoformat()):
            return None
        return value


class CrmBreakdownItem(BaseModel):
    label: str
    total: int
    urgent: int
    expired: int
    expiring_30: int
    expiring_60: int
    expiring_90: int
    potential_value_aed: int


class CrmFilters(BaseModel):
    areas: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    buildings: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)


class CrmAssetBreakdownItem(BaseModel):
    asset_class: CrmAssetClass
    total: int
    urgent: int
    exact_unit_matches: int
    annual_rent_at_risk_aed: int
    property_types: list[str] = Field(default_factory=list)


class CrmCoverage(BaseModel):
    rental_source: str
    rental_start_date: date | None = None
    rental_end_date: date | None = None
    rental_rows: int = 0
    exact_unit_ids_available: bool = False
    exact_unit_matches: int = 0
    data_complete_through: date | None = None
    matching_method: str
    caveat: str


class CrmSummary(BaseModel):
    total_leads: int
    urgent: int
    expired_unlet: int
    expiring_30_days: int
    expiring_31_to_60_days: int
    expiring_61_to_90_days: int
    sale_conversation_candidates: int
    annual_rent_at_risk_aed: int


class CrmDashboardResponse(BaseModel):
    leads: list[CrmLead]
    total: int
    limit: int
    offset: int
    summary: CrmSummary
    asset_breakdown: list[CrmAssetBreakdownItem] = Field(default_factory=list)
    breakdown: list[CrmBreakdownItem]
    breakdown_level: str
    filters: CrmFilters
    coverage: CrmCoverage
    as_of: date


class CrmTimelineEvent(BaseModel):
    event_id: str
    event_type: Literal["lease", "sale"]
    event_date: date
    title: str
    description: str
    amount_aed: int | None = None
    end_date: date | None = None
    source: str
    confidence: MatchConfidence
    ltv_pct: float | None = None
    capital_gain_pct: float | None = None


class CrmRenewalOwner(BaseModel):
    """A manual owner or one unambiguous, verified imported owner."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    source: Literal["workspace", "owner_import"]


class CrmLeadDetailResponse(BaseModel):
    lead: CrmLead
    owner: CrmRenewalOwner | None = None
    timeline: list[CrmTimelineEvent]
    next_best_actions: list[str]
    agent_signals: list[str] = Field(default_factory=list)
    match_explanation: str
    generated_at: datetime


class CrmSavedLead(SQLModel, table=True):
    __tablename__ = "crm_saved_leads"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "organization_id",
            "unit_candidate_key",
            name="uq_crm_saved_lead_owner_candidate",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    lead_id: str = SQLField(index=True)
    unit_candidate_key: str = SQLField(index=True)
    snapshot: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmSavedLeadResponse(BaseModel):
    id: int
    lead: CrmLead
    created_at: datetime
    updated_at: datetime


class CrmLeadWorkspace(SQLModel, table=True):
    __tablename__ = "crm_lead_workspaces"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "organization_id",
            "unit_candidate_key",
            name="uq_crm_workspace_owner_candidate",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    lead_id: str = SQLField(index=True)
    unit_candidate_key: str = SQLField(index=True)
    pipeline_status: str = SQLField(default="new", index=True)
    highlight_color: str = SQLField(default="none")
    owner_name: str | None = None
    owner_email: str | None = None
    owner_phone: str | None = None
    owner_source: str | None = None
    next_follow_up: date | None = None
    tags: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmLeadNote(SQLModel, table=True):
    __tablename__ = "crm_lead_notes"

    id: int | None = SQLField(default=None, primary_key=True)
    workspace_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_lead_workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    body: str = SQLField(sa_column=Column(Text, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmWorkspaceUpdate(BaseModel):
    pipeline_status: CrmPipelineStatus | None = None
    highlight_color: CrmHighlightColor | None = None
    owner_name: str | None = Field(default=None, max_length=200)
    owner_email: str | None = Field(default=None, max_length=320)
    owner_phone: str | None = Field(default=None, max_length=80)
    next_follow_up: date | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


class CrmNoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4_000)


class CrmLeadNoteResponse(BaseModel):
    id: int
    body: str
    created_at: datetime
    updated_at: datetime


class CrmWorkspaceSummary(BaseModel):
    id: int | None = None
    lead_id: str
    unit_candidate_key: str
    pipeline_status: CrmPipelineStatus
    highlight_color: CrmHighlightColor
    owner_name: str | None = None
    owner_email: str | None = None
    owner_phone: str | None = None
    next_follow_up: date | None = None
    tags: list[str] = Field(default_factory=list)
    note_count: int = 0
    updated_at: datetime


class CrmWorkspacePage(BaseModel):
    items: list[CrmWorkspaceSummary]
    total: int
    limit: int
    offset: int


class CrmWorkspaceResponse(CrmWorkspaceSummary):
    notes: list[CrmLeadNoteResponse] = Field(default_factory=list)


class CrmSaleComparable(BaseModel):
    transaction_date: date
    building_name: str
    unit_number: str
    unit_series: str | None = None
    property_type: str
    bedrooms: str
    size_sqft: float
    sale_amount_aed: int
    price_per_sqft_aed: float | None = None
    selection_reason: str


class CrmRentalComparable(BaseModel):
    lease_start: date
    building_name: str
    unit_number: str | None = None
    unit_series: str | None = None
    unit_match_status: str = "unresolved"
    property_type: str
    bedrooms: str
    size_sqft: float
    annual_rent_aed: int
    rent_per_sqft_aed: float | None = None
    selection_reason: str


class CrmReportAnalysis(BaseModel):
    estimated_market_value_aed: int | None = None
    estimated_value_low_aed: int | None = None
    estimated_value_high_aed: int | None = None
    estimated_market_rent_aed: int | None = None
    indicated_capital_change_aed: int | None = None
    indicated_capital_change_pct: float | None = None
    indicative_selling_costs_aed: int | None = None
    indicative_proceeds_before_debt_aed: int | None = None
    estimated_market_gross_yield_pct: float | None = None
    current_rent_vs_market_pct: float | None = None
    target_unit_series: str | None = None
    sales_selection_basis: str
    rental_selection_basis: str
    sales_comparables_used: int = 0
    rental_comparables_used: int = 0
    confidence: MatchConfidence


class CrmPriceIndexPoint(BaseModel):
    quarter: date
    label: str
    dubai_index: float
    dld_index: float | None = None
    transaction_index: float | None = None
    segment_index: float | None = None
    dubai_median_psf_aed: int | None = None
    segment_median_psf_aed: int | None = None
    dld_transactions: int = 0
    transaction_count: int = 0
    segment_transactions: int = 0


class CrmPriceIndex(BaseModel):
    name: str = "Vitevue Dubai Residential Price Index"
    base_period: date
    latest_period: date
    current_index: float
    change_since_base_pct: float
    year_over_year_pct: float | None = None
    current_median_psf_aed: int | None = None
    segment_name: str
    segment_current_index: float | None = None
    segment_year_over_year_pct: float | None = None
    segment_current_median_psf_aed: int | None = None
    points: list[CrmPriceIndexPoint] = Field(default_factory=list)
    methodology: str


class CrmPropertyReportResponse(BaseModel):
    lead: CrmLead
    period_start: date
    period_end: date
    sales_comparables: list[CrmSaleComparable]
    rental_comparables: list[CrmRentalComparable]
    analysis: CrmReportAnalysis
    price_index: CrmPriceIndex
    agent_signals: list[str] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    generated_at: datetime


RENEWAL_FORWARD_DAYS_DEFAULT = 60
RENEWAL_LOOKBACK_DAYS_DEFAULT = 30
# The lease-expiry dataset only covers 90 days ahead (see opportunity_queries._LEAD_CTE).
RENEWAL_FORWARD_DAYS_MAX = 90
RENEWAL_LOOKBACK_DAYS_MAX = 365


class CrmAgentAreaPreference(SQLModel, table=True):
    """One agent's renewal-lead areas and lease-expiry windows within an organization."""

    __tablename__ = "crm_agent_area_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "organization_id",
            name="uq_crm_agent_area_preference_owner",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    areas: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    forward_days: int = SQLField(default=RENEWAL_FORWARD_DAYS_DEFAULT)
    lookback_days: int = SQLField(default=RENEWAL_LOOKBACK_DAYS_DEFAULT)
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmLicensedBroker(SQLModel, table=True):
    """One licensed real-estate broker from the regulator's public list (org-agnostic reference).

    Phones are normalized like owner-sheet phones and emails are casefolded, so a sheet row can be
    compared with them directly. The table is replaced as a whole by ``load_licensed_brokers``."""

    __tablename__ = "crm_licensed_brokers"

    broker_number: int = SQLField(primary_key=True)
    name_key: str = SQLField(index=True)
    phones: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    emails: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    card_expiry_date: date | None = SQLField(default=None)
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmCompanyListing(BaseModel):
    """A listing the agency holds the mandate for, owned by one of its agents.

    Matched first for buyers (sale) and tenants (rent): the agency knows it is available and can
    earn both sides of the deal. Rent prices are yearly, like tenant budgets. Bedrooms use the
    lead brief's numbers (0 = studio). Synthetic rows are test data and can be removed as a set.
    """

    id: int | None = None
    organization_id: str
    reference: str
    agent_user_id: str | None = None
    agent_name: str
    agent_phone: str | None = None
    mode: str
    title: str
    property_type: str
    bedrooms: int | None = None
    size_sqft: int | None = None
    price_aed: int
    area_name: str
    building_name: str | None = None
    unit_number: str | None = None
    status: str = "active"
    is_synthetic: bool = False
    listed_at: datetime
    created_at: datetime
    updated_at: datetime


class CrmCompanyListingSource(SQLModel, table=True):
    """The Property Finder broker selected for an organization's company inventory."""

    __tablename__ = "crm_company_listing_sources"

    organization_id: str = SQLField(
        primary_key=True, foreign_key="organizations.id", ondelete="CASCADE"
    )
    broker_id: str
    broker_name: str
    selected_by_user_id: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmCompanyListingResponse(BaseModel):
    """A company listing as Assets › Company listings shows it."""

    reference: str
    agent_name: str
    agent_phone: str | None
    mode: str
    title: str
    property_type: str
    bedrooms: int | None
    size_sqft: int | None
    price_aed: int
    area_name: str
    building_name: str | None
    unit_number: str | None
    status: str
    listed_at: datetime
    # Property Finder photo URLs; filled for company listing cards and shared collections.
    photos: list[str] = []


class CrmCompanyListingDetail(CrmCompanyListingResponse):
    """One Property Finder listing; `managed` when it belongs to the organization's connected company.

    Only managed listings may carry private owner and agreement documents.
    """

    listing_key: str
    broker_id: str
    broker_name: str
    managed: bool
    # Filled only by `listings_by_keys` (shared collections); other lookups leave them empty.
    description: str | None = None
    updated_at: datetime | None = None


class CrmCompanyListingCompany(BaseModel):
    broker_id: str
    broker_name: str
    listings: int
    agents: int
    last_scraped_at: datetime | None = None


class CrmCompanyListingAgentInventory(BaseModel):
    agent_id: str | None = None
    agent_name: str
    listings: int
    # As published on the agent's Property Finder listings.
    phone: str | None = None
    email: str | None = None


class CrmCompanyListingsResponse(BaseModel):
    company: CrmCompanyListingCompany | None
    matching_company: CrmCompanyListingCompany | None = None
    companies: list[CrmCompanyListingCompany] = Field(default_factory=list)
    agents: list[CrmCompanyListingAgentInventory] = Field(default_factory=list)
    items: list[CrmCompanyListingResponse] = Field(default_factory=list)
    total: int = 0
    limit: int
    offset: int


class CrmCompanyListingSourceUpdate(BaseModel):
    broker_id: str = Field(min_length=1, max_length=80)


class CrmCompanyListingSourceResponse(BaseModel):
    broker_id: str
    broker_name: str


class CrmAreaPreferencesUpdate(BaseModel):
    areas: list[str] = Field(max_length=50)
    forward_days: int = Field(
        default=RENEWAL_FORWARD_DAYS_DEFAULT, ge=1, le=RENEWAL_FORWARD_DAYS_MAX
    )
    lookback_days: int = Field(
        default=RENEWAL_LOOKBACK_DAYS_DEFAULT, ge=0, le=RENEWAL_LOOKBACK_DAYS_MAX
    )


class CrmAreaPreferencesResponse(CrmAreaPreferencesUpdate):
    updated_at: datetime | None = None


class CrmRenewalArea(BaseModel):
    area: str
    upcoming_90_days: int


class CrmRenewalLead(BaseModel):
    lead: CrmLead
    owner: CrmRenewalOwner | None = None
    # The agency's stored lead for this unit, once an agent has opened it in Leads.
    lead_record_id: int | None = None


class CrmRenewalLeadCounts(BaseModel):
    """Lead units in the agent's whole window, whichever page or kind was asked for."""

    all: int = 0
    # Lease still running (ends today or later), soonest first in the feed.
    upcoming: int = 0
    # Lease ended inside the look-back window.
    expired: int = 0
    # Ended with no later lease registered for the exact unit (a subset of expired).
    vacant: int = 0


class CrmRenewalLeadsResponse(BaseModel):
    items: list[CrmRenewalLead]
    # Leads of the requested kind across every page (the pager's total).
    total: int
    limit: int
    offset: int
    # Leases whose expiry crossed into the forward window today.
    entered_today: int
    preferences: CrmAreaPreferencesResponse
    as_of: date
    kind: Literal["all", "upcoming", "expired", "vacant"] = "all"
    counts: CrmRenewalLeadCounts = Field(default_factory=CrmRenewalLeadCounts)


class CrmRenewalsResponse(BaseModel):
    """Assets › Renewals: one page of the lease-expiry dataset and the options for its filters."""

    leads: list[CrmLead]
    total: int
    limit: int
    offset: int
    property_types: list[str] = Field(default_factory=list)
    # Listed once an area is picked.
    projects: list[str] = Field(default_factory=list)
    # Listed once a project is picked.
    buildings: list[str] = Field(default_factory=list)
    as_of: date
    # owner=known: each lease's owner from the owner imports, by unit_candidate_key.
    owners: dict[str, CrmRenewalOwner] = Field(default_factory=dict)
