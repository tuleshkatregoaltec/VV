"""Lead routing rules and the assignment API contract.

A rule is a typed, ordered condition group with one specific-person destination, optionally
followed by more people who get the lead in turn when the one holding it does not act in time.
Conditions are an enumerated field/operator/value list, never an expression, so nothing a manager
types is run.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

from app.crm.inbound_models import AssignmentReason, ImportAssignmentMode

RoutingField = Literal["intent", "source", "area", "language"]
RoutingMatch = Literal["all", "any"]
# "unknown" is missing data, not a value a rule can target.
ROUTABLE_INTENTS = ("buy", "rent", "sell", "let")
MAX_ASSIGNMENT_BATCH = 100
MAX_ROTATION_PEOPLE = 20
# One week: longer than that is not a "first response" rotation.
MAX_ROTATION_MINUTES = 7 * 24 * 60
MAX_AGENT_LANGUAGES = 20


def language_key(value: str | None) -> str:
    """How a language is compared: case- and spacing-insensitive. Never guessed from anything."""
    return " ".join((value or "").split()).casefold()


class CrmRoutingRule(SQLModel, table=True):
    __tablename__ = "crm_routing_rules"
    __table_args__ = (
        CheckConstraint("match_mode IN ('all', 'any')", name="ck_crm_routing_rule_match_mode"),
        CheckConstraint(
            f"rotation_minutes IS NULL OR rotation_minutes BETWEEN 1 AND {MAX_ROTATION_MINUTES}",
            name="ck_crm_routing_rule_rotation_minutes",
        ),
        # The team must belong to the rule's organization; a team with rules cannot be deleted.
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_crm_routing_rule_team",
            ondelete="RESTRICT",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    team_id: str = SQLField(index=True)
    name: str = SQLField(sa_column=Column(String(120), nullable=False))
    enabled: bool = SQLField(default=True, sa_column=Column(Boolean, nullable=False))
    priority: int = SQLField(sa_column=Column(Integer, nullable=False))
    match_mode: str = SQLField(default="all")
    conditions: list[dict[str, Any]] = SQLField(
        default_factory=list, sa_column=Column(JSON, nullable=False)
    )
    destination_user_id: str
    # Who gets the lead next, in order, when the holder neither logs contact nor changes its stage
    # within rotation_minutes. Empty: the destination keeps it (no rotation).
    rotation_user_ids: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default=text("'[]'")),
    )
    rotation_minutes: int | None = SQLField(default=None, sa_column=Column(Integer, nullable=True))
    # Give the lead (and rotate it) only to people recorded as speaking the lead's language.
    # A lead with no language is routed as usual: its language is never guessed.
    speakers_only: bool = SQLField(
        default=False, sa_column=Column(Boolean, nullable=False, server_default=text("false"))
    )
    revision: int = SQLField(default=1, sa_column=Column(Integer, nullable=False))
    created_by_user_id: str
    updated_by_user_id: str
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class RoutingCondition(BaseModel):
    """Matches when the lead's value equals any listed value (case-insensitive).

    `area` compares against the lead's preferred locations and `language` against the contact's
    preferred language (from an imported Language column); a lead with no value never matches.
    """

    field: RoutingField
    operator: Literal["is_any_of"] = "is_any_of"
    values: list[str] = Field(min_length=1, max_length=50)

    @field_validator("values")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        cleaned = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not cleaned:
            raise ValueError("Give at least one value")
        if any(len(value) > 120 for value in cleaned):
            raise ValueError("Values are at most 120 characters")
        return cleaned

    @model_validator(mode="after")
    def _known_intents(self) -> "RoutingCondition":
        if self.field == "intent":
            values = [value.casefold() for value in self.values]
            if unknown := sorted(set(values) - set(ROUTABLE_INTENTS)):
                raise ValueError(f"Unknown intent: {', '.join(unknown)}")
            self.values = values
        return self


class RoutingRuleWrite(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    team_id: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    match_mode: RoutingMatch = "all"
    conditions: list[RoutingCondition] = Field(min_length=1, max_length=10)
    destination_user_id: str = Field(min_length=1, max_length=200)
    rotation_user_ids: list[str] = Field(default_factory=list, max_length=MAX_ROTATION_PEOPLE)
    rotation_minutes: int | None = Field(default=None, ge=1, le=MAX_ROTATION_MINUTES)
    speakers_only: bool = False

    @model_validator(mode="after")
    def _rotation(self) -> "RoutingRuleWrite":
        if bool(self.rotation_user_ids) != (self.rotation_minutes is not None):
            raise ValueError("A rotation needs both the next people and how many minutes each has")
        order = [self.destination_user_id, *self.rotation_user_ids]
        if len(set(order)) != len(order):
            raise ValueError("A person is listed twice in the rotation")
        return self


class RoutingRuleUpdate(RoutingRuleWrite):
    expected_revision: int = Field(ge=1)


class RoutingRuleOrder(BaseModel):
    """Every rule of the organization, first match first, with the revisions the editor saw."""

    rule_ids: list[int] = Field(min_length=1, max_length=500)
    expected_revisions: dict[int, int]


class RoutingRuleResponse(BaseModel):
    id: int
    name: str
    team_id: str
    enabled: bool
    priority: int
    match_mode: RoutingMatch
    conditions: list[RoutingCondition]
    destination_user_id: str
    rotation_user_ids: list[str] = Field(default_factory=list)
    rotation_minutes: int | None = None
    speakers_only: bool = False
    revision: int
    updated_by_user_id: str
    created_at: datetime
    updated_at: datetime


class AssignmentPerson(BaseModel):
    user_id: str
    name: str
    # Languages the person speaks, as a manager recorded them (team members only).
    languages: list[str] = Field(default_factory=list)


class CrmAgentLanguages(SQLModel, table=True):
    """The languages a member speaks, recorded by their manager or an administrator.

    Used only by rules set to "speakers only". Distinct from a lead's language (the contact's
    preferred language from an import); removed with the person's membership.
    """

    __tablename__ = "crm_agent_languages"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_crm_agent_languages_member"),
        ForeignKeyConstraint(
            ["organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            name="fk_crm_agent_languages_membership",
            ondelete="CASCADE",
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str
    languages: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    updated_by_user_id: str
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class AgentLanguagesWrite(BaseModel):
    languages: list[str] = Field(default_factory=list, max_length=MAX_AGENT_LANGUAGES)

    @field_validator("languages")
    @classmethod
    def _clean(cls, values: list[str]) -> list[str]:
        cleaned: dict[str, str] = {}
        for value in values:
            label = " ".join(value.split())
            if len(label) > 60:
                raise ValueError("A language is at most 60 characters")
            if label:
                cleaned.setdefault(language_key(label), label)
        return list(cleaned.values())


class AgentLanguagesResponse(BaseModel):
    user_id: str
    languages: list[str]


class AssignmentTeam(BaseModel):
    id: str
    name: str
    supervised: bool
    members: list[AssignmentPerson]


class MyTeam(BaseModel):
    """A team the signed-in user belongs to (any role): its shared pool is theirs to claim from."""

    id: str
    name: str


class AssignmentCapabilities(BaseModel):
    organization_admin: bool
    can_import: bool
    can_assign: bool
    can_manage_rules: bool
    can_manage_teams: bool


class AssignmentScopeResponse(BaseModel):
    """What the signed-in user may do, and to whom they may assign, derived on the server."""

    capabilities: AssignmentCapabilities
    teams: list[AssignmentTeam]
    my_teams: list[MyTeam] = Field(default_factory=list)
    # Everyone named on a lead the user can see, so an assignee shows by name.
    people: list[AssignmentPerson]


class ImportAssignmentPolicy(BaseModel):
    mode: ImportAssignmentMode
    assignee_user_id: str | None = Field(default=None, max_length=200)
    # "agent": which of the agent's teams owns the leads (needed only when ambiguous). Otherwise
    # the team that owns leads not given to anyone: the pool in "team" mode, else where leads left
    # unassigned wait. Optional when the importer manages exactly one team.
    team_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _assignee_matches_mode(self) -> "ImportAssignmentPolicy":
        if self.mode == "agent" and not self.assignee_user_id:
            raise ValueError("Choose the agent who receives the imported leads")
        if self.mode != "agent" and self.assignee_user_id:
            raise ValueError("An agent is only chosen when assigning to a specific agent")
        if self.mode == "self" and self.team_id:
            raise ValueError("Leads you import for yourself stay with your own team")
        # "self" names no one on purpose: the assignee is the signed-in importer, never the body.
        return self


class LeadAssignmentRequest(BaseModel):
    """Assign (or with null, unassign) a bounded set of leads; all succeed or none change."""

    enquiry_ids: list[int] = Field(min_length=1, max_length=MAX_ASSIGNMENT_BATCH)
    assignee_user_id: str | None = Field(default=None, max_length=200)
    # Which of the assignee's teams owns the leads; needed only when they are in several of yours.
    team_id: str | None = Field(default=None, max_length=200)
    expected_revisions: dict[int, int]

    @model_validator(mode="after")
    def _revision_for_each(self) -> "LeadAssignmentRequest":
        if len(set(self.enquiry_ids)) != len(self.enquiry_ids):
            raise ValueError("A lead is listed twice")
        if set(self.expected_revisions) != set(self.enquiry_ids):
            raise ValueError("Give the revision you saw for every lead")
        return self


class LeadAssignmentResult(BaseModel):
    enquiry_id: int
    assigned_user_id: str | None
    assignment_revision: int
    changed: bool
    team_id: str | None = None
    shared: bool = False


class PoolReleaseRequest(BaseModel):
    """Put unassigned leads in a team's shared pool, all or none."""

    enquiry_ids: list[int] = Field(min_length=1, max_length=MAX_ASSIGNMENT_BATCH)
    team_id: str = Field(min_length=1, max_length=200)
    expected_revisions: dict[int, int]

    @model_validator(mode="after")
    def _revision_for_each(self) -> "PoolReleaseRequest":
        if len(set(self.enquiry_ids)) != len(self.enquiry_ids):
            raise ValueError("A lead is listed twice")
        if set(self.expected_revisions) != set(self.enquiry_ids):
            raise ValueError("Give the revision you saw for every lead")
        return self


class LeadAssignmentResponse(BaseModel):
    results: list[LeadAssignmentResult]


class AssignmentEventResponse(BaseModel):
    id: int
    previous_user_id: str | None
    assigned_user_id: str | None
    actor_user_id: str
    reason: AssignmentReason
    rule_id: int | None = None
    rule_revision: int | None = None
    import_id: int | None = None
    team_id: str | None = None
    revision: int
    created_at: datetime


RotationStatus = Literal["active", "stopped", "finished"]


class CrmLeadRotation(SQLModel, table=True):
    """A lead moving through a rule's people until one acts on it in time.

    The order and timeout are copied from the rule when the lead is routed, so editing or deleting
    the rule does not change a rotation already running. `assignment_revision` is the lead's
    revision when this rotation last assigned it: any other change of assignee (a manager's
    reassignment, a claim) makes them differ, and the rotation then stops instead of overriding it.
    """

    __tablename__ = "crm_lead_rotations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'stopped', 'finished')", name="ck_crm_lead_rotation_status"
        ),
        ForeignKeyConstraint(
            ["team_id", "organization_id"],
            ["organization_teams.id", "organization_teams.organization_id"],
            name="fk_crm_lead_rotation_team",
            ondelete="CASCADE",
        ),
        # The scheduler's scan: only running rotations, soonest first.
        Index(
            "ix_crm_lead_rotations_due",
            "due_at",
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    enquiry_id: int = SQLField(
        sa_column=Column(
            ForeignKey("crm_inbound_enquiries.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        )
    )
    team_id: str
    rule_id: int | None = None
    rule_revision: int | None = None
    user_ids: list[str] = SQLField(sa_column=Column(JSON, nullable=False))
    # Everyone who has held the lead under this rotation (the rule's people it was given to and
    # anyone a manager handed it to meanwhile): never given it again by the rotation.
    tried_user_ids: list[str] = SQLField(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, server_default=text("'[]'")),
    )
    # Set by a "speakers only" rule: the lead's language (normalized) each next person must speak.
    required_language: str | None = None
    position: int = SQLField(default=0, sa_column=Column(Integer, nullable=False))
    timeout_minutes: int = SQLField(sa_column=Column(Integer, nullable=False))
    due_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    assignment_revision: int = SQLField(sa_column=Column(Integer, nullable=False))
    status: str = SQLField(default="active")
    stop_reason: str | None = None
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class MemberWorkload(BaseModel):
    """Recorded facts only: no ratings, response-time scores or rankings are computed."""

    user_id: str
    name: str
    open_leads: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    # Assigned, never contacted yet, and past the first-response deadline the lead carries.
    awaiting_first_contact: int = 0
    overdue_first_contact: int = 0
    last_activity_at: datetime | None = None


class TeamWorkload(BaseModel):
    team_id: str
    name: str
    unassigned: int = 0
    shared: int = 0
    members: list[MemberWorkload]


class WorkloadResponse(BaseModel):
    teams: list[TeamWorkload]
