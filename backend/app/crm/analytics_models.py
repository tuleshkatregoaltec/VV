"""Agent lead analytics for managers: recorded facts per person, no ratings or rankings."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

AnalyticsDays = Literal[7, 30, 90]
SourceKind = Literal["marketing", "vitevue_lease", "vitevue_sold", "own"]


class AgentLeadMetrics(BaseModel):
    user_id: str
    name: str
    team_ids: list[str] = Field(default_factory=list)
    # Current open work (same rules as Team workload).
    open_leads: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    awaiting_first_contact: int = 0
    overdue_first_contact: int = 0
    # Distinct leads with a logged contact by this person in the last 24 hours.
    contacted_24h: int = 0
    # Over leads assigned to this person within the window (minutes, rounded).
    avg_first_response_minutes: int | None = None
    # From a lead's release to the team pool until this person claimed it, within the window.
    avg_claim_minutes: int | None = None
    assigned_in_window: int = 0
    qualified_or_better: int = 0
    last_activity_at: datetime | None = None


class TeamAnalyticsResponse(BaseModel):
    days: int
    generated_at: datetime
    agents: list[AgentLeadMetrics]


class SourceCount(BaseModel):
    kind: SourceKind
    label: str
    count: int


class DailyActivity(BaseModel):
    date: date
    calls: int = 0
    messages: int = 0
    meetings: int = 0


class AgentLeadRow(BaseModel):
    id: int
    name: str
    status: str
    source: str
    source_kind: SourceKind
    assigned_at: datetime | None = None
    first_contact_at: datetime | None = None
    last_contact_at: datetime | None = None
    next_follow_up: date | None = None
    overdue: bool = False


class AgentAnalyticsDetail(BaseModel):
    days: int
    metrics: AgentLeadMetrics
    sources: list[SourceCount]
    activity: list[DailyActivity]
    leads: list[AgentLeadRow]
