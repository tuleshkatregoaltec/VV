"""The CRM Assistant evaluation cases: schema, CRM-only tool registry and loader.

Every case is written against the synthetic fixture (crm_fixture.py) and carries:
- `expect`: what a model run must do, checked deterministically where possible (workflows,
  required tools, access outcome, clarification, whether a write proposal is allowed, that
  writes need confirmation) plus answer facts and forbidden claims for the answer text.
- `probe`: the reference check that grounds `expect` in the real CRM. It runs the same tool or
  service the assistant would use, as the case's actor, against a disposable database seeded
  with the fixture, and checks access, counts, refusals and persisted state before and after
  confirmation. `none` marks a case with nothing in the CRM to probe (a market question).

The registries below mirror the code (app/crm/assistant, app/assistant_actions); the offline
tests fail if they drift. This module imports no application code, so loading the cases needs
no settings, database or network.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scripts.evaluations.crm_assistant import crm_fixture as fixture

BENCHMARK = Path(__file__).with_name("crm_benchmark.json")

Role = Literal["owner", "manager", "agent"]
Workflow = Literal["crm", "followup", "action"]
Category = Literal[
    "lead_read",
    "deal_read",
    "team_read",
    "followup",
    "calendar",
    "action",
    "team_action",
    "permission",
    "tenant_isolation",
    "clarification",
    "stale_context",
    "unsupported",
    "security",
]
Outcome = Literal["answer", "clarify", "refuse", "unsupported"]
Write = Literal["none", "proposal", "refused"]

# The coordinator's workflow tools (app/crm/assistant/agent.py) and each specialist's tools
# (app/crm/assistant/workflows.py).
WORKFLOW_TOOLS = {
    "retrieve_personal_crm": "crm",
    "plan_followups": "followup",
    "prepare_action": "action",
}
READ_TOOLS = frozenset(
    {"query_my_crm_records", "query_my_calendar", "query_my_lead_emails", "hold_pending_request"}
)
SPECIALIST_TOOLS: dict[str, frozenset[str]] = {
    "crm": READ_TOOLS,
    "followup": READ_TOOLS,
    "action": frozenset(
        {
            "query_my_crm_records",
            "query_my_calendar",
            "hold_pending_request",
            "find_assignment_colleagues",
            "find_meeting_colleagues",
            "find_teams",
            "find_team_people",
            "propose_crm_action",
        }
    ),
}
CRM_TOOLS = frozenset(WORKFLOW_TOOLS).union(*SPECIALIST_TOOLS.values())
# Market AI's tools (app/market_ai). None may ever be reachable from the CRM Assistant.
MARKET_TOOLS = frozenset(
    {
        "analyze_pricing",
        "comparable_evidence",
        "compare_stored_projects",
        "get_database_coverage",
        "get_listing_inventory",
        "get_market_pulse",
        "get_project_delivery_summary",
        "get_project_profile",
        "get_similar_projects",
        "query_market_metrics",
        "rank_areas",
        "research_listing_shortlist",
        "research_market",
        "search_database_locations",
    }
)
# app.crm.assistant.models.CrmAssistantResource
RESOURCES = frozenset(
    {
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
        "team_workload",
        "teams",
    }
)
# app.assistant_actions.models.ActionKind
ACTION_KINDS = frozenset(
    {
        "create_lead",
        "update_lead",
        "assign_lead",
        "unassign_lead",
        "delete_lead",
        "log_contact",
        "release_to_pool",
        "add_note",
        "create_reminder",
        "update_reminder",
        "delete_reminder",
        "schedule_viewing",
        "cancel_viewing",
        "create_listing_draft",
        "update_listing_draft",
        "send_message",
        "publish_listing",
        "book_external_viewing",
        "book_calendar_meeting",
        "create_team",
        "delete_team",
        "add_team_agent",
        "remove_team_member",
        "set_team_manager",
        "move_team_agent",
        "reschedule_calendar_event",
        "cancel_calendar_event",
    }
)
# app.assistant_actions.models.ActionStatus, plus the HTTP refusal a confirmation itself can get
# (for example once the user has left the organization).
FINAL_STATUSES = frozenset(
    {
        "awaiting_confirmation",
        "succeeded",
        "partially_succeeded",
        "cancelled",
        "expired",
        "failed",
        "not_connected",
        "queued",
        "unknown",
        "error:403",
        "error:404",
    }
)
LOOKUP_TOOLS = Literal[
    "find_assignment_colleagues", "find_meeting_colleagues", "find_teams", "find_team_people"
]
# State a probe can observe, by subject kind (see crm_probes.observe).
STATE_FIELDS = {
    "lead": {
        "assigned_to",
        "team",
        "status",
        "in_pool",
        "notes",
        "activities",
        "next_follow_up",
        "intent",
    },
    "team": {"members", "exists"},
    "team_named": {"exists"},
    "event": {"exists", "date", "time", "end_date", "end_time"},
    "events_titled": {"count", "date", "time", "end_date", "end_time"},
    "leads_named": {"count"},
    "reminder": {"exists", "title", "due_at"},
    "listing": {"title", "price_aed"},
    "reminders": {"count"},
    "viewings": {"count"},
    "listing_drafts": {"count"},
    "outbox": {"count"},
    "actions": {"count"},
}
MUTATIONS = Literal[
    "reassign_lead",
    "set_lead_status",
    "remove_team_member",
    "remove_membership",
    "suspend_organization",
    "expire_actions",
    "delete_event",
]

Keys = list[Annotated[str, Field(min_length=1, max_length=40)]]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Expectation(Strict):
    """What a model run must do. Deterministic: workflows, tools, write and confirmation (from
    tool calls and the actions table). Text checks: answer_facts and forbidden_claims."""

    outcome: Outcome
    workflows: list[Workflow] = Field(max_length=2)
    tools: list[str]
    write: Write = "none"
    action_kind: str | None = None
    confirmation_required: bool = False
    answer_facts: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    forbidden_claims: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)

    @model_validator(mode="after")
    def consistent(self):
        if len(set(self.workflows)) != len(self.workflows):
            raise ValueError("Each workflow is listed once")
        allowed = frozenset().union(*(SPECIALIST_TOOLS[w] for w in self.workflows))
        if not set(self.tools) <= allowed:
            raise ValueError(f"Tools {sorted(set(self.tools) - allowed)} are not in its workflows")
        if self.outcome == "unsupported" and (self.workflows or self.tools):
            raise ValueError("An unsupported request runs no CRM workflow or tool")
        if (self.write == "none") != (self.action_kind is None):
            raise ValueError("action_kind is set exactly when a write is expected or refused")
        if self.action_kind is not None and self.action_kind not in ACTION_KINDS:
            raise ValueError(f"Unknown action kind {self.action_kind}")
        if self.write != "none" and "action" not in self.workflows:
            raise ValueError("Writes are prepared only by the action workflow")
        if self.write == "proposal" and "propose_crm_action" not in self.tools:
            raise ValueError("A proposal needs propose_crm_action")
        if self.confirmation_required != (self.write == "proposal"):
            raise ValueError("Every write proposal, and only a proposal, needs confirmation")
        return self


class ReadExpect(Strict):
    available: bool = True
    total: int | None = None
    counts_by_status: dict[str, int] | None = None
    counts_by_team: dict[str, int] | None = None
    counts_by_handler: dict[str, int] | None = None
    counts_by_assignment: dict[str, int] | None = None
    # Fixture keys of the returned rows (leads L.., deals D.., teams, events): exact set.
    records: Keys | None = None
    includes: Keys = Field(default_factory=list)
    # Fixture keys whose names must not appear anywhere in the result.
    excludes: Keys = Field(default_factory=list)
    page: dict[str, Any] | None = None
    limitation_contains: str | None = None


class ReadProbe(Strict):
    type: Literal["read"]
    query: dict[str, Any]
    expect: ReadExpect

    @model_validator(mode="after")
    def known_resource(self):
        if self.query.get("resource") not in RESOURCES:
            raise ValueError("Unknown CRM resource")
        return self


class CalendarProbe(Strict):
    type: Literal["calendar"]
    start: date
    end: date
    events: Keys
    excludes: Keys = Field(default_factory=list)


class EmailProbe(Strict):
    type: Literal["lead_emails"]
    lead: str
    available: bool
    total: int | None = None


class LookupProbe(Strict):
    type: Literal["lookup"]
    tool: LOOKUP_TOOLS
    search: str = Field(min_length=2, max_length=80)
    available: bool = True
    matches: Keys = Field(default_factory=list)
    clarification_required: bool | None = None
    reason_contains: str | None = None


class Lookup(Strict):
    tool: LOOKUP_TOOLS
    search: str = Field(min_length=2, max_length=80)


class Mutation(Strict):
    """A change made by someone else between proposal and confirmation."""

    op: MUTATIONS
    lead: str | None = None
    person: str | None = None
    team: str | None = None
    event: str | None = None
    status: str | None = None
    to: str | None = None


class StateCheck(Strict):
    """A persisted fact: `before` holds before the proposal and still after it (nothing is
    written until confirmation); `after` holds once the decision is made. Leaving `after` out
    means unchanged (an explicit null is a value, such as an unassigned lead)."""

    subject: str = Field(pattern=r"^[a-z_]+:.+$")
    field: str
    before: Any = None
    after: Any = None

    @property
    def expected_after(self) -> Any:
        return self.after if "after" in self.model_fields_set else self.before

    @model_validator(mode="after")
    def known_field(self):
        kind = self.subject.split(":", 1)[0]
        if self.field not in STATE_FIELDS.get(kind, set()):
            raise ValueError(f"{self.subject} has no observable field {self.field}")
        return self


class ActionProbe(Strict):
    type: Literal["action"]
    lookups: list[Lookup] = Field(default_factory=list)
    kind: str
    payload: dict[str, Any]
    proposal: Literal["created", "refused"]
    reason_contains: str | None = None
    between: list[Mutation] = Field(default_factory=list)
    decision: Literal["confirm", "cancel", "none"] = "none"
    final_status: str | None = None
    state: list[StateCheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if self.kind not in ACTION_KINDS:
            raise ValueError(f"Unknown action kind {self.kind}")
        if self.proposal == "refused" and (self.decision != "none" or self.between):
            raise ValueError("A refused proposal has nothing to confirm")
        if (self.decision == "none") != (self.final_status is None):
            raise ValueError("final_status is given exactly when a decision is made")
        if self.final_status is not None and self.final_status not in FINAL_STATUSES:
            raise ValueError(f"Unknown final status {self.final_status}")
        return self


class PendingProbe(Strict):
    """A request held between turns is rechecked: it survives only while still allowed."""

    type: Literal["pending"]
    kind: str | None = None
    lead: str
    held: bool
    between: list[Mutation] = Field(default_factory=list)
    still_held: bool


class GuardProbe(Strict):
    """The question itself is refused by the chat input guard before any model call."""

    type: Literal["input_guard"]


class NoProbe(Strict):
    type: Literal["none"]
    reason: str = Field(min_length=10)


Probe = Annotated[
    ReadProbe
    | CalendarProbe
    | EmailProbe
    | LookupProbe
    | ActionProbe
    | PendingProbe
    | GuardProbe
    | NoProbe,
    Field(discriminator="type"),
]


class CrmCase(Strict):
    id: str = Field(pattern=r"^crm[0-9]{3}$")
    category: Category
    role: Role
    actor: str
    question: str = Field(min_length=8, max_length=600)
    expect: Expectation
    probe: Probe

    @model_validator(mode="after")
    def grounded(self):
        if self.actor not in fixture.PEOPLE:
            raise ValueError(f"{self.id}: unknown actor {self.actor}")
        if fixture.role_of(self.actor) != self.role:
            raise ValueError(f"{self.id}: {self.actor} is not a CRM {self.role}")
        probe = self.probe
        if isinstance(probe, ActionProbe):
            expected = self.expect.action_kind
            if expected is not None and expected != probe.kind:
                raise ValueError(f"{self.id}: probe kind differs from the expected action")
            if self.expect.write == "proposal" and probe.proposal != "created":
                raise ValueError(f"{self.id}: an allowed write must be creatable")
            if self.expect.write == "refused" and probe.proposal != "refused":
                raise ValueError(f"{self.id}: a refused write must be refused by the CRM")
        elif self.expect.write != "none" and not isinstance(probe, LookupProbe | PendingProbe):
            raise ValueError(f"{self.id}: a write case needs an action, lookup or pending probe")
        if isinstance(probe, GuardProbe) and self.expect.outcome not in {"refuse", "unsupported"}:
            raise ValueError(f"{self.id}: a guarded question cannot expect an answer")
        _check_refs(self.id, probe.model_dump())
        return self


_REF_TABLES = {
    "lead": fixture.LEADS,
    "person": fixture.PEOPLE,
    "team": fixture.TEAMS,
    "event": fixture.EVENTS,
    "reminder": fixture.REMINDERS,
    "viewing": fixture.VIEWINGS,
    "listing": fixture.LISTING_DRAFTS,
}
_KEY_TABLES = {
    **fixture.LEADS,
    **fixture.DEALS,
    **fixture.TEAMS,
    **fixture.EVENTS,
    **fixture.PEOPLE,
    **fixture.REMINDERS,
    **fixture.VIEWINGS,
    **fixture.LISTING_DRAFTS,
}
# Free text as the user would say it (a team's spoken name, a search): only "@" references
# inside these are fixture keys.
_FREE_TEXT = {"query", "payload", "search"}


def _check_refs(case_id: str, value: Any, key: str | None = None) -> None:
    """Every fixture reference in a probe must exist, so no probe silently checks nothing."""
    if isinstance(value, dict):
        for name, item in value.items():
            _check_refs(
                case_id, item, "free_text" if name in _FREE_TEXT or key == "free_text" else name
            )
    elif isinstance(value, list):
        for item in value:
            _check_refs(case_id, item, key)
    elif isinstance(value, str):
        if value.startswith("@"):
            kind, _, ref = value[1:].partition(":")
            if ref not in _REF_TABLES.get(kind, {}):
                raise ValueError(f"{case_id}: unknown fixture reference {value}")
        elif key in {"records", "includes", "excludes", "events", "matches"}:
            if value not in _KEY_TABLES:
                raise ValueError(f"{case_id}: unknown fixture key {value}")
        elif key in {"lead", "person", "team", "event", "to"} and value not in _KEY_TABLES:
            raise ValueError(f"{case_id}: unknown fixture key {value}")
        elif key == "subject":
            kind, _, ref = value.partition(":")
            table = {
                "lead": fixture.LEADS,
                "team": fixture.TEAMS,
                "event": fixture.EVENTS,
                "reminder": fixture.REMINDERS,
                "listing": fixture.LISTING_DRAFTS,
                "reminders": fixture.PEOPLE,
                "viewings": fixture.PEOPLE,
                "listing_drafts": fixture.PEOPLE,
                "outbox": fixture.PEOPLE,
                "actions": fixture.PEOPLE,
            }.get(kind)
            if table is not None and ref not in table:
                raise ValueError(f"{case_id}: unknown state subject {value}")


class CrmBenchmark(Strict):
    version: Literal[2]
    assistant: Literal["crm"]
    fixture: Literal["crm-eval-agency-v1"]
    reference_date: date
    cases: list[CrmCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_and_dated(self):
        if self.reference_date != fixture.REFERENCE_DATE:
            raise ValueError("The benchmark and fixture must share one reference date")
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("CRM benchmark case IDs must be unique")
        if len({case.question.casefold() for case in self.cases}) != len(self.cases):
            raise ValueError("CRM benchmark questions must be unique")
        return self

    @property
    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()


def load_crm_benchmark(path: Path = BENCHMARK) -> CrmBenchmark:
    return CrmBenchmark.model_validate_json(path.read_text())


def summary(benchmark: CrmBenchmark) -> dict[str, Any]:
    """Counts only: what the cases cover, never their text."""

    def count(values) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            result[value] = result.get(value, 0) + 1
        return dict(sorted(result.items()))

    cases = benchmark.cases
    return {
        "version": benchmark.version,
        "fixture": benchmark.fixture,
        "reference_date": benchmark.reference_date.isoformat(),
        "sha256": benchmark.digest,
        "cases": len(cases),
        "by_category": count(case.category for case in cases),
        "by_role": count(case.role for case in cases),
        "by_outcome": count(case.expect.outcome for case in cases),
        "by_write": count(case.expect.write for case in cases),
        "by_probe": count(case.probe.type for case in cases),
        "action_kinds": count(c.expect.action_kind for c in cases if c.expect.action_kind),
        "resources": count(
            c.probe.query["resource"] for c in cases if isinstance(c.probe, ReadProbe)
        ),
    }
