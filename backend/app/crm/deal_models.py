"""CRM deals: an agreed transaction on a lead, moved through the Dubai conveyancing steps.

A deal belongs to the agent who holds it and that agent's team, so visibility follows lead
assignment (agent: own; manager: supervised teams; administrator: the organization). Every
creation, stage move and close is an event, which the manager view counts as activity.
Documents, commission splits, forms, compliance and approvals are not stored yet.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

DealType = Literal["sale", "rent"]
DealStatus = Literal["open", "won", "lost"]
DealOrigin = Literal[
    "listing",
    "owner_outreach",
    "renewal",
    "portal",
    "ads",
    "own_contact",
    "agent_to_agent",
    "inbound",
]

# The conveyancing steps of a Dubai sale and a let. The last step closes the deal as won.
DEAL_STAGES: dict[str, list[str]] = {
    "sale": [
        "Offer accepted",
        "Form F signed",
        "Mortgage / bank",
        "NOC",
        "Transfer booked",
        "Transferred",
    ],
    "rent": ["Contract", "Deposit and cheques", "Ejari", "Keys"],
}

ORIGIN_LABELS: dict[str, str] = {
    "listing": "Listing",
    "owner_outreach": "Owner outreach",
    "renewal": "Renewal / lease",
    "portal": "Portal",
    "ads": "Ads",
    "own_contact": "Own contact / referral",
    "agent_to_agent": "Agent for a client",
    "inbound": "Other inbound",
}


class CrmDeal(SQLModel, table=True):
    __tablename__ = "crm_deals"
    __table_args__ = (
        Index("ix_crm_deals_org_agent_status", "organization_id", "assigned_user_id", "status"),
        Index("ix_crm_deals_org_team", "organization_id", "team_id"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str
    lead_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    assigned_user_id: str | None = None
    team_id: str | None = None
    created_by_user_id: str
    deal_type: str
    unit: str
    client: str
    counterparty: str = ""
    value_aed: int | None = SQLField(default=None, sa_column=Column(BigInteger, nullable=True))
    due_date: date | None = None
    listing_id: str | None = None
    origin: str
    # The lead's source label when the deal was made, kept for the record.
    origin_source: str = ""
    stage_index: int = 0
    status: str = "open"
    dld_transaction_id: str | None = None
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    closed_at: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))


class CrmDealEvent(SQLModel, table=True):
    __tablename__ = "crm_deal_events"
    __table_args__ = (
        Index("ix_crm_deal_events_org_actor_at", "organization_id", "actor_user_id", "created_at"),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str
    deal_id: int = SQLField(
        sa_column=Column(
            Integer, ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False, index=True
        )
    )
    actor_user_id: str
    kind: str  # created | stage | edited | closed | reopened
    from_stage: int | None = None
    to_stage: int | None = None
    detail: dict = SQLField(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


# ── API ──


class DealCreateRequest(BaseModel):
    lead_id: int = Field(gt=0)
    listing_id: str | None = Field(default=None, max_length=120)
    value_aed: int | None = Field(default=None, ge=0, le=100_000_000_000)
    due_date: date | None = None
    counterparty: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=200)


class DealUpdateRequest(BaseModel):
    value_aed: int | None = Field(default=None, ge=0, le=100_000_000_000)
    due_date: date | None = None
    counterparty: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=200)
    dld_transaction_id: str | None = Field(default=None, max_length=80)


class DealMoveRequest(BaseModel):
    direction: Literal["next", "back"]
    # The stage the screen showed; a stale move (someone else moved it meanwhile) is refused.
    expected_stage_index: int = Field(ge=0)


class DealCloseRequest(BaseModel):
    outcome: Literal["lost", "reopen"]
    reason: str | None = Field(default=None, max_length=500)


class DealResponse(BaseModel):
    id: int
    reference: str
    deal_type: DealType
    unit: str
    client: str
    counterparty: str
    value_aed: int | None
    due_date: date | None
    listing_id: str | None
    lead_id: int | None
    agent_user_id: str | None
    team_id: str | None
    origin: DealOrigin
    origin_label: str
    origin_source: str
    stages: list[str]
    stage_index: int
    stage: str
    next_stage: str | None
    status: DealStatus
    dld_transaction_id: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class DealListResponse(BaseModel):
    items: list[DealResponse]
    counts: dict[str, int]
    open_value_aed: int


class DealEventResponse(BaseModel):
    kind: str
    actor_user_id: str
    from_stage: str | None
    to_stage: str | None
    detail: dict
    created_at: datetime


class AgentDealSummary(BaseModel):
    user_id: str | None
    open: int
    won_30d: int
    lost_30d: int
    open_value_aed: int
    average_value_aed: int
    by_stage: dict[str, int]
    by_origin: dict[str, int]
    last_activity_at: datetime | None


class DealOversightResponse(BaseModel):
    """Deals of the agents this user oversees (own only for an agent)."""

    scope: Literal["own", "teams", "organization"]
    agents: list[AgentDealSummary]
    totals: AgentDealSummary
    origin_labels: dict[str, str]
