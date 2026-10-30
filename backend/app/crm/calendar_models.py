from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text
from sqlmodel import JSON, Column, SQLModel
from sqlmodel import Field as SQLField

CalendarKind = Literal["viewing", "call", "follow_up", "deal_date", "deadline"]
CalendarRepeat = Literal["none", "daily", "weekly", "monthly", "yearly"]
CalendarShowAs = Literal["busy", "free"]
CalendarVisibility = Literal["default", "public", "private", "confidential"]
GoogleSyncStatus = Literal["local", "pending", "synced", "error"]

TIME_PATTERN = r"^(?:[01]\d|2[0-3]):[0-5]\d$"


class CrmCalendarConnection(SQLModel, table=True):
    """One Google Calendar account per CRM user, keyed by (organization_id, user_id)."""

    __tablename__ = "crm_calendar_connections"

    organization_id: str = SQLField(primary_key=True)
    user_id: str = SQLField(primary_key=True)
    google_email: str
    refresh_token_encrypted: str = SQLField(sa_column=Column(Text, nullable=False))
    sync_token: str | None = SQLField(default=None, sa_column=Column(Text, nullable=True))
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CrmCalendarEvent(SQLModel, table=True):
    __tablename__ = "crm_calendar_events"
    __table_args__ = (
        Index("ix_crm_calendar_events_owner_date", "organization_id", "user_id", "event_date"),
        Index(
            "ix_crm_calendar_events_google_id", "organization_id", "user_id", "google_event_id"
        ),
    )

    id: int | None = SQLField(default=None, primary_key=True)
    organization_id: str = SQLField(index=True)
    user_id: str = SQLField(index=True)
    title: str
    event_date: date
    event_time: str | None = None
    event_end_date: date | None = None
    event_end_time: str | None = None
    all_day: bool = False
    repeat: str = "none"
    meet: bool = False
    meet_link: str | None = None
    meet_request_id: str | None = None
    location: str = ""
    reminders: list[int] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    reminders_use_default: bool = False
    guests: list[str] = SQLField(default_factory=list, sa_column=Column(JSON, nullable=False))
    guests_can_modify: bool = False
    guests_can_invite_others: bool = True
    guests_can_see_other_guests: bool = True
    show_as: str = "busy"
    visibility: str = "default"
    kind: str = "follow_up"
    detail: str = SQLField(default="", sa_column=Column(Text, nullable=False, server_default=""))
    lead_id: int | None = SQLField(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("crm_inbound_enquiries.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )
    listing_id: str | None = None
    done: bool = False
    google_event_id: str | None = None
    etag: str | None = None
    google_sync_status: str = SQLField(default="local", index=True)
    updated_at: datetime = SQLField(sa_column=Column(DateTime(timezone=True), nullable=False))


class CalendarEventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    date: date
    time: str | None = Field(default=None, pattern=TIME_PATTERN)
    end_date: date | None = None
    end_time: str | None = Field(default=None, pattern=TIME_PATTERN)
    all_day: bool = False
    repeat: CalendarRepeat = "none"
    meet: bool = False
    location: str = Field(default="", max_length=500)
    reminders: list[int] = Field(default_factory=lambda: [30], max_length=5)
    reminders_use_default: bool = False
    guests: list[str] = Field(default_factory=list, max_length=50)
    guests_can_modify: bool = False
    guests_can_invite_others: bool = True
    guests_can_see_other_guests: bool = True
    show_as: CalendarShowAs = "busy"
    visibility: CalendarVisibility = "default"
    kind: CalendarKind
    detail: str = Field(default="", max_length=2000)
    lead_id: int | None = Field(default=None, ge=1)
    listing_id: str | None = Field(default=None, max_length=160)


class CalendarViewingCreate(BaseModel):
    date: date
    time: str = Field(pattern=TIME_PATTERN)
    listing_id: str | None = Field(default=None, max_length=160)
    note: str = Field(default="", max_length=2000)


class CalendarEventMove(BaseModel):
    date: date
    time: str | None = Field(default=None, pattern=TIME_PATTERN)


class CalendarEventResponse(BaseModel):
    id: int
    date: str
    time: str | None
    end_date: str
    end_time: str | None
    all_day: bool
    repeat: CalendarRepeat
    meet: bool
    meet_link: str | None
    location: str
    reminders: list[int]
    reminders_use_default: bool
    guests: list[str]
    guests_can_modify: bool
    guests_can_invite_others: bool
    guests_can_see_other_guests: bool
    show_as: CalendarShowAs
    visibility: CalendarVisibility
    kind: CalendarKind
    title: str
    detail: str
    agent: str
    lead_id: int | None
    deal_id: str | None
    listing_id: str | None
    owner_id: str | None
    context: str | None
    record: dict[str, Any] | None
    outcome: str | None
    google_sync_status: GoogleSyncStatus
