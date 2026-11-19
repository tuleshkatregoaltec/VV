from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CrmAssistantResource = Literal[
    "leads",
    "renewals",
    "owner_properties",
    "saved_leads",
    "lead_workspaces",
    "owner_workspaces",
    "deals",
    "lead_notes",
    "lead_activities",
    "workspace_notes",
    "owner_notes",
    "matches",
    "reminders",
    "viewings",
    "listing_drafts",
]


class CrmAssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: CrmAssistantResource
    search: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    follow_up_before: date | None = None
    # Leads/renewals only: narrow a manager's or administrator's wider view.
    assignment: Literal["mine", "colleagues", "unassigned"] | None = None
    record_id: int | None = Field(default=None, ge=1)
    summary_only: bool = False
    include_contact_details: bool = False
    limit: int = Field(default=20, ge=1, le=50)
    offset: int = Field(default=0, ge=0, le=10000)

    @model_validator(mode="after")
    def applicable_filters(self):
        if self.follow_up_before and self.resource not in {
            "leads",
            "lead_workspaces",
            "owner_workspaces",
        }:
            raise ValueError("This resource does not store follow-up dates")
        if self.assignment and self.resource not in {"leads", "renewals"}:
            raise ValueError("Only leads and renewals can be filtered by assignment")
        if self.status and self.resource in {
            "saved_leads",
            "deals",
            "lead_notes",
            "lead_activities",
            "workspace_notes",
            "owner_notes",
            "matches",
            "reminders",
            "viewings",
            "listing_drafts",
        }:
            raise ValueError("This resource does not store a queryable status")
        return self


class CrmAssistantResult(BaseModel):
    resource: CrmAssistantResource
    source: str = "Your CRM records (PostgreSQL)"
    available: bool = True
    scope: str = "Records your CRM role lets you see in your current organization"
    total: int | None = None
    counts_by_status: dict[str, int] = Field(default_factory=dict)
    records: list[dict[str, Any]] = Field(default_factory=list)
    limit: int
    offset: int
    limitations: list[str] = Field(default_factory=list)
