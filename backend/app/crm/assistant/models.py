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
    # Managers and administrators only: the CRM's team workload (crm/oversight.py).
    "team_workload",
    # The CRM's own team view (crm/assignment.scope_response): every team for an
    # administrator, a manager's teams with their members, the names of an agent's own teams.
    "teams",
]
# Resources that have a handler (assignee) and an owning team.
HANDLED_RESOURCES = {"leads", "renewals", "deals"}
# Resources narrowed by a team's name.
TEAM_FILTERED_RESOURCES = HANDLED_RESOURCES | {"teams", "team_workload"}


class CrmAssistantQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource: CrmAssistantResource
    search: str | None = Field(default=None, min_length=1, max_length=120)
    status: str | None = Field(default=None, min_length=1, max_length=40)
    follow_up_before: date | None = None
    # Leads/renewals/deals only: narrow a manager's or administrator's wider view.
    assignment: Literal["mine", "colleagues", "unassigned"] | None = None
    # Leads/renewals/deals only: a colleague's name as the user gave it (start of the name).
    handled_by: str | None = Field(default=None, min_length=2, max_length=80)
    # Leads/renewals/deals, teams and team_workload: a team's name, matched exactly
    # (case-insensitive), ignoring the words "CRM" and "team".
    team: str | None = Field(default=None, min_length=1, max_length=80)
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
        if (self.assignment or self.handled_by) and self.resource not in HANDLED_RESOURCES:
            raise ValueError("Only leads, renewals and deals can be filtered by handler")
        if self.team and self.resource not in TEAM_FILTERED_RESOURCES:
            raise ValueError("Only leads, renewals, deals, teams and team workload take a team")
        if self.resource in {"team_workload", "teams"} and (
            self.search or self.status or self.record_id or self.include_contact_details
        ):
            raise ValueError("Teams and team workload take only a team name")
        if self.status and self.resource in {
            "saved_leads",
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
    # Leads/renewals only; None means this resource has no such classification.
    counts_by_record_kind: dict[str, int] | None = None
    counts_by_intent: dict[str, int] | None = None
    # Leads/renewals only: "mine", "colleagues", "unassigned", as the assignment filter defines.
    counts_by_assignment: dict[str, int] | None = None
    # Leads/renewals/deals: the same matches by owning team name and by handler name
    # ("you", a colleague's name, or "unassigned").
    counts_by_team: dict[str, int] | None = None
    counts_by_handler: dict[str, int] | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    limit: int
    offset: int
    limitations: list[str] = Field(default_factory=list)
