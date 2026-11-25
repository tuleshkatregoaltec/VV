from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import BigInteger, DateTime, UniqueConstraint
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

from app.crm.calendar_models import TIME_PATTERN
from app.crm.inbound_models import InboundIntent, InboundStatus


class ActionKind(StrEnum):
    CREATE_LEAD = "create_lead"
    UPDATE_LEAD = "update_lead"
    ASSIGN_LEAD = "assign_lead"
    # Removes the assignee and keeps the lead (with its team); never a deletion.
    UNASSIGN_LEAD = "unassign_lead"
    # Kept so stored proposals still load; the CRM cannot delete leads, so it is always refused.
    DELETE_LEAD = "delete_lead"
    # Logs a contact attempt, as the CRM's lead page does; on a lead in the pool of a team the
    # user belongs to, the first logged contact takes the lead for them.
    LOG_CONTACT = "log_contact"
    # A manager or administrator shares the lead, unassigned, in its own team's pool.
    RELEASE_TO_POOL = "release_to_pool"
    ADD_NOTE = "add_note"
    CREATE_REMINDER = "create_reminder"
    UPDATE_REMINDER = "update_reminder"
    DELETE_REMINDER = "delete_reminder"
    SCHEDULE_VIEWING = "schedule_viewing"
    CANCEL_VIEWING = "cancel_viewing"
    CREATE_LISTING_DRAFT = "create_listing_draft"
    UPDATE_LISTING_DRAFT = "update_listing_draft"
    SEND_MESSAGE = "send_message"
    PUBLISH_LISTING = "publish_listing"
    BOOK_EXTERNAL_VIEWING = "book_external_viewing"
    # A meeting on the user's own calendar, optionally naming colleagues; no invitations.
    BOOK_CALENDAR_MEETING = "book_calendar_meeting"
    # Team management, as the CRM's Teams page (organization owners and administrators only).
    CREATE_TEAM = "create_team"
    DELETE_TEAM = "delete_team"
    ADD_TEAM_AGENT = "add_team_agent"
    REMOVE_TEAM_MEMBER = "remove_team_member"
    SET_TEAM_MANAGER = "set_team_manager"
    # Moves an agent from one team to another (organization owners and administrators only).
    MOVE_TEAM_AGENT = "move_team_agent"
    # The user's own CRM calendar events, as CRM › Calendar moves and deletes them.
    RESCHEDULE_CALENDAR_EVENT = "reschedule_calendar_event"
    CANCEL_CALENDAR_EVENT = "cancel_calendar_event"


ActionStatus = Literal[
    "awaiting_confirmation",
    "succeeded",
    # The CRM change was saved but its external delivery (Google Calendar) was not.
    "partially_succeeded",
    "cancelled",
    "expired",
    "failed",
    "not_connected",
    "queued",
    "unknown",
]


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateLead(StrictPayload):
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=80)
    email: str | None = Field(default=None, max_length=320)
    intent: InboundIntent = "unknown"
    notes: str | None = Field(default=None, max_length=4000)


class LeadTarget(StrictPayload):
    lead_id: int = Field(gt=0)


class UpdateLead(LeadTarget):
    status: InboundStatus | None = None
    intent: InboundIntent | None = None
    next_follow_up: date | None = None
    lost_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def require_change(self):
        fields = self.model_fields_set - {"lead_id"}
        if not fields:
            raise ValueError("At least one lead field is required")
        if any(getattr(self, field) is None for field in fields & {"status", "intent"}):
            raise ValueError("Status and intent cannot be null")
        return self


class AssignLead(LeadTarget):
    assignee_id: str = Field(min_length=1, max_length=128)


class AddNote(LeadTarget):
    body: str = Field(min_length=1, max_length=4000)


class LogContact(LeadTarget):
    # The CRM's own activity types (crm/inbound_models.InboundActivityCreate).
    activity_type: Literal["contact_attempt", "call", "email", "whatsapp", "meeting"]
    body: str | None = Field(default=None, min_length=1, max_length=4000)


class CreateReminder(StrictPayload):
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime
    lead_id: int | None = Field(default=None, gt=0)


class UpdateReminder(StrictPayload):
    reminder_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime


class DeleteReminder(StrictPayload):
    reminder_id: int = Field(gt=0)


class ScheduleViewing(LeadTarget):
    title: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Viewing end must follow its start")
        return self


class CalendarMeeting(StrictPayload):
    title: str = Field(min_length=1, max_length=200)
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    location: str | None = Field(default=None, max_length=500)
    lead_id: int | None = Field(default=None, gt=0)
    # Organization members named in the event details only; they are not invited.
    colleague_ids: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("Meeting end must follow its start")
        if len(set(self.colleague_ids)) != len(self.colleague_ids):
            raise ValueError("Each colleague may be named once")
        return self


class CancelViewing(StrictPayload):
    viewing_id: int = Field(gt=0)


class CreateListingDraft(StrictPayload):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8000)
    price_aed: int = Field(gt=0, le=100_000_000_000)
    location: str = Field(min_length=1, max_length=500)


class UpdateListingDraft(CreateListingDraft):
    listing_id: int = Field(gt=0)


class SendMessage(LeadTarget):
    channel: Literal["email", "sms", "whatsapp"]
    body: str = Field(min_length=1, max_length=4000)
    # Email only; a plain default is used when omitted.
    subject: str | None = Field(default=None, min_length=1, max_length=300)


class PublishListing(StrictPayload):
    listing_id: int = Field(gt=0)


class CreateTeam(StrictPayload):
    # As the CRM's TeamWriteRequest.
    name: str = Field(min_length=1, max_length=120)


class TeamTarget(StrictPayload):
    team_id: str = Field(min_length=1, max_length=200)


class TeamMemberChange(TeamTarget):
    # An organization member's ID (from the team people lookup). Not named user_id: the
    # answer guard treats that name as an internal identifier.
    member_id: str = Field(min_length=1, max_length=200)


class SetTeamManager(TeamMemberChange):
    # True: the team's other managers leave the team (they stay in the organization).
    replace_existing: bool = False


class TeamTransfer(StrictPayload):
    member_id: str = Field(min_length=1, max_length=200)
    from_team_id: str = Field(min_length=1, max_length=200)
    to_team_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def different_teams(self):
        if self.from_team_id == self.to_team_id:
            raise ValueError("Choose two different teams")
        return self


class CalendarEventTarget(StrictPayload):
    event_id: int = Field(gt=0)


class RescheduleCalendarEvent(CalendarEventTarget):
    # As the CRM's CalendarEventMove: a new start date and time (HH:MM, Dubai), or no time for
    # all day; the event keeps its length.
    date: date
    time: str | None = Field(default=None, pattern=TIME_PATTERN)


Payload = (
    CreateLead
    | UpdateLead
    | AssignLead
    | LeadTarget
    | AddNote
    | LogContact
    | CreateReminder
    | UpdateReminder
    | DeleteReminder
    | ScheduleViewing
    | CalendarMeeting
    | CancelViewing
    | CreateListingDraft
    | UpdateListingDraft
    | SendMessage
    | PublishListing
    | CreateTeam
    | TeamTransfer
    | RescheduleCalendarEvent
    | CalendarEventTarget
    | SetTeamManager
    | TeamMemberChange
    | TeamTarget
)
PAYLOAD_TYPES = {
    ActionKind.CREATE_LEAD: CreateLead,
    ActionKind.UPDATE_LEAD: UpdateLead,
    ActionKind.ASSIGN_LEAD: AssignLead,
    ActionKind.UNASSIGN_LEAD: LeadTarget,
    ActionKind.DELETE_LEAD: LeadTarget,
    ActionKind.ADD_NOTE: AddNote,
    ActionKind.LOG_CONTACT: LogContact,
    ActionKind.RELEASE_TO_POOL: LeadTarget,
    ActionKind.CREATE_REMINDER: CreateReminder,
    ActionKind.UPDATE_REMINDER: UpdateReminder,
    ActionKind.DELETE_REMINDER: DeleteReminder,
    ActionKind.SCHEDULE_VIEWING: ScheduleViewing,
    ActionKind.CANCEL_VIEWING: CancelViewing,
    ActionKind.CREATE_LISTING_DRAFT: CreateListingDraft,
    ActionKind.UPDATE_LISTING_DRAFT: UpdateListingDraft,
    ActionKind.SEND_MESSAGE: SendMessage,
    ActionKind.PUBLISH_LISTING: PublishListing,
    ActionKind.BOOK_EXTERNAL_VIEWING: ScheduleViewing,
    ActionKind.BOOK_CALENDAR_MEETING: CalendarMeeting,
    ActionKind.CREATE_TEAM: CreateTeam,
    ActionKind.DELETE_TEAM: TeamTarget,
    ActionKind.ADD_TEAM_AGENT: TeamMemberChange,
    ActionKind.REMOVE_TEAM_MEMBER: TeamMemberChange,
    ActionKind.SET_TEAM_MANAGER: SetTeamManager,
    ActionKind.MOVE_TEAM_AGENT: TeamTransfer,
    ActionKind.RESCHEDULE_CALENDAR_EVENT: RescheduleCalendarEvent,
    ActionKind.CANCEL_CALENDAR_EVENT: CalendarEventTarget,
}


class ActionProposalRequest(StrictPayload):
    kind: ActionKind
    conversation_id: int = Field(gt=0)
    payload: Payload
    idempotency_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")

    @model_validator(mode="before")
    @classmethod
    def validate_kind_payload(cls, value):
        if isinstance(value, dict) and "kind" in value and "payload" in value:
            value = dict(value)
            payload = value["payload"]
            if isinstance(payload, BaseModel):
                payload = payload.model_dump(exclude_unset=True)
            value["payload"] = PAYLOAD_TYPES[ActionKind(value["kind"])].model_validate(payload)
        return value


class ActionProposalResponse(BaseModel):
    id: str
    kind: ActionKind
    status: ActionStatus
    title: str
    preview: dict[str, Any]
    created_at: datetime
    expires_at: datetime
    result: dict[str, Any] | None = None


class AssistantAction(SQLModel, table=True):
    __tablename__ = "assistant_actions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "organization_id", "idempotency_key", name="uq_assistant_action_idempotency"
        ),
    )

    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    conversation_id: int = SQLField(index=True)
    kind: str
    status: str = SQLField(index=True)
    idempotency_key: str
    request_hash: str
    payload: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    snapshot: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    preview: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    result: dict[str, Any] | None = SQLField(default=None, sa_column=Column(JSON))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    expires_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: datetime | None = SQLField(
        default=None, sa_column=Column(DateTime(timezone=True))
    )


class AssistantReminder(SQLModel, table=True):
    __tablename__ = "assistant_reminders"
    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    lead_id: int | None = None
    title: str
    due_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class AssistantViewing(SQLModel, table=True):
    __tablename__ = "assistant_viewings"
    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    lead_id: int
    title: str
    location: str
    status: str = "scheduled"
    starts_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    ends_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class AssistantListingDraft(SQLModel, table=True):
    __tablename__ = "assistant_listing_drafts"
    id: int | None = SQLField(default=None, primary_key=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    title: str
    description: str
    price_aed: int = SQLField(sa_column=Column(BigInteger, nullable=False))
    location: str
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class AssistantOutbox(SQLModel, table=True):
    __tablename__ = "assistant_outbox"
    id: str = SQLField(default_factory=lambda: str(uuid4()), primary_key=True)
    action_id: str = SQLField(unique=True, index=True)
    user_id: str = SQLField(index=True)
    organization_id: str = SQLField(index=True)
    kind: str
    status: str = "not_connected"
    payload: dict[str, Any] = SQLField(sa_column=Column(JSON, nullable=False))
    created_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))
    claimed_at: datetime | None = SQLField(default=None, sa_column=Column(DateTime(timezone=True)))


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int | None
    title: str
    due_at: datetime


class ViewingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lead_id: int
    title: str
    location: str
    status: str
    starts_at: datetime
    ends_at: datetime
    delivery: Literal["internal_only"] = "internal_only"


class ListingDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    description: str
    price_aed: int
    location: str
    publication: Literal["draft_only"] = "draft_only"
