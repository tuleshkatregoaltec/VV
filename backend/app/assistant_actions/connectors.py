"""Live connectors for confirmed assistant actions: Brevo email and Google Calendar.

Only two external kinds have a connector, each only when it is ready:

- send_message on the email channel, when Brevo is configured on the server. The recipient is
  the lead's own address on file, resolved here from the authorized lead, never from the model.
- book_external_viewing, when the signed-in user has connected their Google Calendar. The event
  is created on that user's CRM calendar and pushed to Google by the calendar service.
- book_calendar_meeting, always: the meeting is created on the user's own CRM calendar, and pushed
  to their Google Calendar when connected. Named colleagues are written in its details only;
  nobody is invited.

Everything else (SMS, WhatsApp, publishing a listing) stays recorded as not connected.
Dispatch follows service.dispatch_confirmed: the outbox claim becomes "unknown" before any network
call, so an ambiguous outcome is never retried automatically.
"""

from zoneinfo import ZoneInfo

import httpx
from sqlmodel import col

from app.assistant_actions.delivery import DeliveryOutcome
from app.assistant_actions.models import ActionKind, CalendarMeeting, ScheduleViewing, SendMessage
from app.crm import brevo, calendar_service
from app.crm.calendar_models import CrmCalendarConnection
from app.crm.email_models import EmailSendCreate
from app.crm.inbound_models import CrmInboundEnquiry

DUBAI = ZoneInfo("Asia/Dubai")
DEFAULT_SUBJECT = "Following up on your enquiry"


async def google_connection(db, *, user_id: str, organization_id: str):
    if not calendar_service.configured():
        return None
    return await db.get(CrmCalendarConnection, (organization_id, user_id))


def dubai_span(starts_at, ends_at) -> str:
    start, end = starts_at.astimezone(DUBAI), ends_at.astimezone(DUBAI)
    until = f"{end:%H:%M}" if end.date() == start.date() else f"{end:%d %b %Y %H:%M}"
    return f"{start:%d %b %Y %H:%M}–{until} Dubai time"


async def readiness(db, kind, payload, *, user_id: str, organization_id: str, contact=None):
    """(ready, delivery line, consequence line) for the confirmation card."""
    if kind == ActionKind.SEND_MESSAGE and payload.channel == "email":
        if not brevo.is_configured():
            return False, "Email (Brevo) is not configured; nothing will be sent", None
        if contact is not None and not (contact.email or "").strip():
            return False, "This lead has no email address; nothing will be sent", None
        if contact is not None and contact.do_not_contact:
            return False, "This lead is marked do not contact; nothing will be sent", None
        return (
            True,
            "Sent through Brevo after you confirm",
            "Sends one email to this lead's email address on file. It appears on the lead's "
            "Conversation tab and in Email › Tracking.",
        )
    if kind == ActionKind.BOOK_EXTERNAL_VIEWING:
        connection = await google_connection(db, user_id=user_id, organization_id=organization_id)
        if connection is None:
            return False, "Google Calendar is not connected; nothing will be booked", None
        return (
            True,
            f"Added to your Google Calendar ({connection.google_email}) after you confirm",
            "Creates this viewing on your CRM calendar and in your Google Calendar. No "
            "invitations are sent to the client.",
        )
    if kind == ActionKind.BOOK_CALENDAR_MEETING:
        connection = await google_connection(db, user_id=user_id, organization_id=organization_id)
        delivery = (
            f"Saved on your CRM calendar and added to your Google Calendar "
            f"({connection.google_email}) after you confirm"
            if connection is not None
            else "Saved on your CRM calendar after you confirm; Google Calendar is not connected"
        )
        return (
            True,
            delivery,
            "Adds this meeting to your own calendar. Named colleagues appear in its details "
            "only; no invitations are sent.",
        )
    if kind in {ActionKind.RESCHEDULE_CALENDAR_EVENT, ActionKind.CANCEL_CALENDAR_EVENT}:
        connection = await google_connection(db, user_id=user_id, organization_id=organization_id)
        verb = "Moved" if kind == ActionKind.RESCHEDULE_CALENDAR_EVENT else "Deleted"
        delivery = (
            f"{verb} on your CRM calendar and in your Google Calendar "
            f"({connection.google_email}) after you confirm"
            if connection is not None
            else f"{verb} on your CRM calendar after you confirm; Google Calendar is not connected"
        )
        consequence = (
            "Moves this event to the new time, keeping its length, as CRM › Calendar does. "
            "No invitations or updates are sent to guests."
            if kind == ActionKind.RESCHEDULE_CALENDAR_EVENT
            else "Deletes this event from your calendar, as CRM › Calendar does. This cannot "
            "be undone. No cancellation messages are sent."
        )
        return True, delivery, consequence
    return False, "No connector configured; nothing will be sent or published", None


class BrevoEmailAdapter:
    def __init__(self, db, *, user_id: str, organization_id: str):
        self.db, self.user_id, self.organization_id = db, user_id, organization_id

    async def dispatch(self, *, payload: SendMessage, idempotency_key: str) -> DeliveryOutcome:
        from app.crm import email_pipeline

        batch = await email_pipeline.send_emails(
            self.db,
            organization_id=self.organization_id,
            user_id=self.user_id,
            payload=EmailSendCreate(
                enquiry_ids=[payload.lead_id],
                subject=payload.subject or DEFAULT_SUBJECT,
                body=payload.body,
            ),
            # The claim re-authorized this lead as the user's own; never widen past it.
            visible=col(CrmInboundEnquiry.id) == payload.lead_id,
        )
        result = batch.results[0] if batch.results else None
        if result and result.ok:
            return DeliveryOutcome(status="succeeded", message=f"Email sent to {result.email}")
        error = (result.error if result else None) or "Brevo did not accept the email"
        return DeliveryOutcome(status="failed", message=f"Email not sent: {error}")


def calendar_outcome(event: dict, when: str) -> DeliveryOutcome:
    """What happened to a CRM calendar event, from its own stored sync state.

    create_event commits the CRM event before any Google call, so reaching here means the CRM
    event is saved. Google Calendar is reported as updated only when the event synced.
    """
    sync = event.get("google_sync_status")
    if sync == "synced":
        return DeliveryOutcome(
            status="succeeded",
            message=f"Saved on your CRM calendar and added to your Google Calendar for {when}",
        )
    if sync == "local":
        return DeliveryOutcome(
            status="succeeded",
            message=f"Saved on your CRM calendar for {when}. Google Calendar is not connected, "
            "so it was not updated.",
        )
    return DeliveryOutcome(
        status="partially_succeeded",
        message=(
            f"Saved on your CRM calendar for {when}, but Google Calendar was not updated "
            "(sync failed). Open CRM › Calendar and press Sync."
        ),
    )


class GoogleCalendarAdapter:
    def __init__(self, db, *, user_id: str, organization_id: str):
        self.db, self.user_id, self.organization_id = db, user_id, organization_id

    async def dispatch(self, *, payload: ScheduleViewing, idempotency_key: str) -> DeliveryOutcome:
        start = payload.starts_at.astimezone(DUBAI)
        end = payload.ends_at.astimezone(DUBAI)
        event = await calendar_service.create_event(
            self.db,
            user_id=self.user_id,
            organization_id=self.organization_id,
            title=payload.title,
            event_date=start.date(),
            event_time=start.strftime("%H:%M"),
            end_date=end.date(),
            end_time=end.strftime("%H:%M"),
            kind="viewing",
            location=payload.location,
            lead_id=payload.lead_id,
        )
        return calendar_outcome(event, dubai_span(payload.starts_at, payload.ends_at))


class CalendarMeetingAdapter:
    def __init__(
        self, db, *, user_id: str, organization_id: str, person_name=None, invitations=None
    ):
        self.db, self.user_id, self.organization_id = db, user_id, organization_id
        # The actions service's verified display-name lookup and its invitation plan
        # (meeting_invitations), passed in: this module must not import the service that
        # dispatches it.
        self.person_name = person_name
        self.invitations = invitations

    async def dispatch(self, *, payload: CalendarMeeting, idempotency_key: str) -> DeliveryOutcome:
        start = payload.starts_at.astimezone(DUBAI)
        end = payload.ends_at.astimezone(DUBAI)
        names = [
            await self.person_name(item) if self.person_name else "A colleague"
            for item in payload.colleague_ids
        ]
        # Exactly the confirmed plan: its colleagues and the lead at a usable address become
        # attendees, and Meet is requested, only through a connected Google Calendar.
        plan = (
            await self.invitations(
                self.db, payload, user_id=self.user_id, organization_id=self.organization_id
            )
            if self.invitations
            else {"invited": [], "emails": {}, "lead": None, "meet": False}
        )
        guests = [
            (names[payload.colleague_ids.index(item)], plan["emails"][item])
            for item in plan["invited"]
        ]
        lead = plan.get("lead") or {}
        if lead.get("email"):
            guests.append((lead["name"], lead["email"]))
        event = await calendar_service.create_event(
            self.db,
            user_id=self.user_id,
            organization_id=self.organization_id,
            title=payload.title,
            event_date=start.date(),
            event_time=start.strftime("%H:%M"),
            end_date=end.date(),
            end_time=end.strftime("%H:%M"),
            kind="meeting",
            detail=f"With {', '.join(names)}" if names else "",
            location=payload.location or "",
            lead_id=payload.lead_id,
            guests=[email for _, email in guests],
            meet=plan["meet"],
        )
        outcome = calendar_outcome(event, dubai_span(payload.starts_at, payload.ends_at))
        synced = event.get("google_sync_status") == "synced"
        notes = []
        if guests:
            invited = ", ".join(name for name, _ in guests)
            notes.append(
                f"Google Calendar sent an invitation to {invited}."
                if synced
                else f"No invitation has been sent to {invited}; Google Calendar sends it only "
                "once the event syncs."
            )
        if plan["meet"]:
            # Only a link Google returned is a Meet link.
            link = event.get("meet_link")
            notes.append(
                f"Google Meet link: {link}"
                if synced and link
                else "No Google Meet link was created."
            )
        if not notes:
            return outcome
        return DeliveryOutcome(status=outcome.status, message=" ".join([outcome.message, *notes]))


class CalendarEventAdapter:
    """Reschedule or delete one of the user's own events through CRM › Calendar's service.

    The calendar commits the CRM change and syncs Google itself; the outcome reports exactly
    what it did. A failure is never reported as done.
    """

    def __init__(self, db, kind, *, user_id: str, organization_id: str):
        self.db, self.kind = db, kind
        self.user_id, self.organization_id = user_id, organization_id

    async def dispatch(self, *, payload, idempotency_key: str) -> DeliveryOutcome:
        event = await calendar_service.get_event(
            self.db, id=payload.event_id, user_id=self.user_id, organization_id=self.organization_id
        )
        if event is None:
            return DeliveryOutcome(
                status="failed", message="The event is no longer on your calendar"
            )
        title = event.title
        connection = (
            await self.db.get(CrmCalendarConnection, (self.organization_id, self.user_id))
            if calendar_service.configured()
            else None
        )
        if self.kind == ActionKind.CANCEL_CALENDAR_EVENT:
            try:
                await calendar_service.delete_event(self.db, event=event, connection=connection)
            except (httpx.HTTPError, RuntimeError):
                # Google refused before anything was deleted: the event is still there.
                await self.db.rollback()
                return DeliveryOutcome(
                    status="failed",
                    message=f"Could not delete {title} from Google Calendar, so it was not "
                    "deleted. Try again from CRM › Calendar.",
                )
            return DeliveryOutcome(
                status="succeeded", message=f"Deleted {title} from your calendar"
            )
        calendar_service.move_event(event, payload.date, payload.time)
        moved = await calendar_service.update_event(self.db, event=event, connection=connection)
        when = f"{payload.date.day} {payload.date:%b %Y}" + (
            f" {payload.time} Dubai time" if payload.time else ", all day"
        )
        sync = moved.get("google_sync_status")
        if sync == "synced":
            return DeliveryOutcome(
                status="succeeded",
                message=f"Moved {title} to {when} on your CRM calendar and Google Calendar",
            )
        if sync == "local":
            return DeliveryOutcome(
                status="succeeded",
                message=f"Moved {title} to {when} on your CRM calendar. Google Calendar is not "
                "connected, so it was not updated.",
            )
        return DeliveryOutcome(
            status="partially_succeeded",
            message=f"Moved {title} to {when} on your CRM calendar, but Google Calendar was not "
            "updated (sync failed). Open CRM › Calendar and press Sync.",
        )


def adapter_for(
    db, kind, *, user_id: str, organization_id: str, person_name=None, invitations=None
):
    owner = {"user_id": user_id, "organization_id": organization_id}
    if kind in {ActionKind.RESCHEDULE_CALENDAR_EVENT, ActionKind.CANCEL_CALENDAR_EVENT}:
        return CalendarEventAdapter(db, kind, **owner)
    if kind == ActionKind.SEND_MESSAGE:
        return BrevoEmailAdapter(db, **owner)
    if kind == ActionKind.BOOK_EXTERNAL_VIEWING:
        return GoogleCalendarAdapter(db, **owner)
    if kind == ActionKind.BOOK_CALENDAR_MEETING:
        return CalendarMeetingAdapter(db, **owner, person_name=person_name, invitations=invitations)
    raise ValueError(f"No connector for {kind}")
