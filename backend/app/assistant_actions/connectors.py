"""Live connectors for confirmed assistant actions: Brevo email and Google Calendar.

Only two external kinds have a connector, each only when it is ready:

- send_message on the email channel, when Brevo is configured on the server. The recipient is
  the lead's own address on file, resolved here from the authorized lead, never from the model.
- book_external_viewing, when the signed-in user has connected their Google Calendar. The event
  is created on that user's CRM calendar and pushed to Google by the calendar service.

Everything else (SMS, WhatsApp, publishing a listing) stays recorded as not connected.
Dispatch follows service.dispatch_confirmed: the outbox claim becomes "unknown" before any network
call, so an ambiguous outcome is never retried automatically.
"""

from zoneinfo import ZoneInfo

from sqlmodel import col

from app.assistant_actions.delivery import DeliveryOutcome
from app.assistant_actions.models import ActionKind, ScheduleViewing, SendMessage
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
        when = f"{start:%d %b %Y %H:%M} Dubai time"
        if event.get("google_sync_status") == "synced":
            return DeliveryOutcome(
                status="succeeded", message=f"Added to your Google Calendar for {when}"
            )
        return DeliveryOutcome(
            status="failed",
            message=(
                f"Saved on your CRM calendar for {when}, but Google Calendar did not accept it. "
                "Open CRM › Calendar and press Sync."
            ),
        )


def adapter_for(db, kind, *, user_id: str, organization_id: str):
    owner = {"user_id": user_id, "organization_id": organization_id}
    if kind == ActionKind.SEND_MESSAGE:
        return BrevoEmailAdapter(db, **owner)
    if kind == ActionKind.BOOK_EXTERNAL_VIEWING:
        return GoogleCalendarAdapter(db, **owner)
    raise ValueError(f"No connector for {kind}")
