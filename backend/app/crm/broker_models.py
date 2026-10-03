"""Bounded broker tools and a persisted proposal requiring a separate human confirmation."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import DateTime, ForeignKey, Text
from sqlmodel import Column, SQLModel
from sqlmodel import Field as SQLField

from app.crm.inbound_models import InboundIntent, InboundStatus

BrokerScope = Literal["mine", "organization"]


class BrokerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    scope: BrokerScope = "mine"


class BrokerListRequest(BrokerRequest):
    intent: InboundIntent | None = None
    statuses: list[InboundStatus] | None = Field(default=None, min_length=1, max_length=14)
    order: Literal["due", "latest"] = Field(
        default="due",
        description="latest: recorded enquiry_date descending, then ID descending. due: follow-up date ascending, nulls last, then ID ascending.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=25,
        description="Requested number of records, e.g. 5 for latest five; counts always cover the full authorized filter.",
    )
    offset: int = Field(default=0, ge=0, le=500)


class BrokerEnquiryRequest(BrokerRequest):
    enquiry_id: int = Field(gt=0)


class BrokerRequirements(BaseModel):
    """Additional constraints intersect the stored enquiry brief; they never replace it."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    locations: list[str] | None = Field(default=None, min_length=1, max_length=5)
    building: str | None = Field(default=None, min_length=1, max_length=160)
    project: str | None = Field(default=None, min_length=1, max_length=160)
    property_type: str | None = Field(default=None, min_length=1, max_length=80)
    bedrooms_min: int | None = Field(default=None, ge=0, le=10)
    bedrooms_max: int | None = Field(default=None, ge=0, le=10)
    budget_min_aed: float | None = Field(default=None, ge=0, le=1_000_000_000)
    budget_max_aed: float | None = Field(default=None, gt=0, le=1_000_000_000)
    budget_min_inclusive: bool = Field(
        default=True,
        description="False: strictly above the minimum. True: at least (equality included).",
    )
    budget_max_inclusive: bool = Field(
        default=True,
        description="False: strictly below the maximum, never up to. True: at most (equality included).",
    )

    @model_validator(mode="after")
    def valid_ranges(self):
        for lower, upper in (
            ("bedrooms_min", "bedrooms_max"),
            ("budget_min_aed", "budget_max_aed"),
        ):
            low, high = getattr(self, lower), getattr(self, upper)
            if low is not None and high is not None and low > high:
                raise ValueError(f"{lower} cannot exceed {upper}")
        if self.locations and any(not name.strip() or len(name) > 160 for name in self.locations):
            raise ValueError("Locations must be nonblank and at most 160 characters")
        return self


class BrokerMatchRequest(BrokerEnquiryRequest):
    requirements: BrokerRequirements | None = None
    refresh: bool = False
    limit: int = Field(default=10, ge=1, le=20)


class BrokerFollowUpRequest(BrokerRequest):
    mode: Literal["daily", "viewing_brief", "draft_message"] = "daily"
    enquiry_id: int | None = Field(default=None, gt=0)
    match_id: int | None = Field(default=None, gt=0)
    due_before: date | None = None
    limit: int = Field(default=20, ge=1, le=25)

    @model_validator(mode="after")
    def required_brief_fields(self):
        if self.mode != "daily" and self.enquiry_id is None:
            raise ValueError("A viewing brief or draft message requires enquiry_id")
        if self.mode == "daily" and (self.enquiry_id is not None or self.match_id is not None):
            raise ValueError("Use viewing_brief or draft_message for a specific enquiry")
        if self.mode != "daily" and self.due_before is not None:
            raise ValueError("due_before only applies to the daily summary")
        return self


class BrokerActionRequest(BrokerEnquiryRequest):
    action: Literal["note", "follow_up"]
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    due_date: date | None = None

    @model_validator(mode="after")
    def required_action_fields(self):
        if self.body is not None and not self.body.strip():
            raise ValueError("Note body must not be blank")
        if self.action == "note" and (not self.body or self.due_date is not None):
            raise ValueError("A note requires body and cannot include due_date")
        if self.action == "follow_up" and self.due_date is None:
            raise ValueError("A follow_up requires due_date")
        return self


class BrokerActionConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: UUID


class CrmBrokerAction(SQLModel, table=True):
    __tablename__ = "crm_broker_actions"

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str = SQLField(index=True)
    enquiry_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_inbound_enquiries.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
    )
    scope: str = "mine"
    kind: str
    body: str | None = SQLField(default=None, sa_column=Column(Text))
    next_follow_up: date | None = None
    expected_updated_at: datetime = SQLField(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    status: str = "proposed"
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class BrokerActionProposal(BaseModel):
    proposal_id: UUID
    enquiry_id: int
    scope: BrokerScope
    action: Literal["note", "follow_up"]
    body: str | None
    due_date: date | None
    status: Literal["proposed", "completed"]
    expected_updated_at: datetime
    created_at: datetime


class BrokerActionResult(BaseModel):
    status: Literal["proposal", "completed"]
    proposal: BrokerActionProposal
    requires_confirmation: bool | None = None
    already_completed: bool | None = None
