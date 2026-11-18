"""The assistant's live connectors: a confirmed email goes through Brevo, a confirmed viewing to
Google Calendar, each only when ready, once, to records the server resolved itself."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.assistant_actions import connectors, service
from app.assistant_actions.adapters import DeliveryOutcome
from app.assistant_actions.models import (
    ActionKind,
    ActionProposalRequest,
    AssistantAction,
    ScheduleViewing,
    SendMessage,
)
from app.crm import brevo, calendar_service, email_pipeline
from app.crm.email_models import EmailSendBatchResponse, EmailSendResult

EMAIL = SendMessage(lead_id=7, channel="email", body="Hello", subject="Your viewing")
VIEWING = ScheduleViewing(
    lead_id=7,
    title="Viewing · Marina Gate",
    starts_at=datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc),
    ends_at=datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc),
    location="Marina Gate 2, Dubai Marina",
)


def contact(email="sara@example.com", do_not_contact=False):
    return SimpleNamespace(email=email, do_not_contact=do_not_contact, full_name="Sara Khan")


class Db:
    def __init__(self, connection=None):
        self.connection, self.added, self.commits = connection, [], 0

    async def get(self, model, key):
        return self.connection

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1

    @asynccontextmanager
    async def begin_nested(self):
        yield


OWNER = {"user_id": "omar", "organization_id": "org"}


# ── readiness: what the confirmation card promises ──


async def test_email_is_ready_only_with_brevo_and_a_reachable_address(monkeypatch):
    monkeypatch.setattr(brevo, "is_configured", lambda: True)
    ready, delivery, consequence = await connectors.readiness(
        Db(), ActionKind.SEND_MESSAGE, EMAIL, **OWNER, contact=contact()
    )
    assert ready and "Brevo" in delivery and "email address on file" in consequence

    for who in (contact(email=None), contact(email="  "), contact(do_not_contact=True)):
        ready, delivery, _ = await connectors.readiness(
            Db(), ActionKind.SEND_MESSAGE, EMAIL, **OWNER, contact=who
        )
        assert not ready and "nothing will be sent" in delivery

    monkeypatch.setattr(brevo, "is_configured", lambda: False)
    ready, delivery, _ = await connectors.readiness(
        Db(), ActionKind.SEND_MESSAGE, EMAIL, **OWNER, contact=contact()
    )
    assert not ready and "not configured" in delivery


async def test_sms_and_whatsapp_messages_stay_disconnected(monkeypatch):
    monkeypatch.setattr(brevo, "is_configured", lambda: True)
    for channel in ("sms", "whatsapp"):
        message = SendMessage(lead_id=7, channel=channel, body="Hi")
        ready, _, _ = await connectors.readiness(
            Db(), ActionKind.SEND_MESSAGE, message, **OWNER, contact=contact()
        )
        assert not ready


async def test_a_booking_is_ready_only_with_the_users_google_connection(monkeypatch):
    monkeypatch.setattr(calendar_service, "configured", lambda: True)
    linked = SimpleNamespace(google_email="omar@example.com")
    ready, delivery, _ = await connectors.readiness(
        Db(connection=linked), ActionKind.BOOK_EXTERNAL_VIEWING, VIEWING, **OWNER
    )
    assert ready and "omar@example.com" in delivery
    ready, delivery, _ = await connectors.readiness(
        Db(connection=None), ActionKind.BOOK_EXTERNAL_VIEWING, VIEWING, **OWNER
    )
    assert not ready and "not connected" in delivery


async def test_publishing_a_listing_has_no_connector():
    ready, delivery, _ = await connectors.readiness(
        Db(), ActionKind.PUBLISH_LISTING, SimpleNamespace(), **OWNER
    )
    assert not ready and "No connector" in delivery


# ── adapters ──


async def test_email_goes_only_to_the_authorized_lead(monkeypatch):
    seen = {}

    async def send(db, *, organization_id, user_id, payload, visible):
        seen.update(org=organization_id, user=user_id, payload=payload, visible=visible)
        return EmailSendBatchResponse(
            sent=1,
            failed=0,
            results=[EmailSendResult(enquiry_id=7, email="sara@example.com", ok=True, error=None)],
        )

    monkeypatch.setattr(email_pipeline, "send_emails", send)
    outcome = await connectors.BrevoEmailAdapter(Db(), **OWNER).dispatch(
        payload=EMAIL, idempotency_key="action-1"
    )
    assert outcome == DeliveryOutcome(status="succeeded", message="Email sent to sara@example.com")
    assert seen["payload"].enquiry_ids == [7] and seen["payload"].subject == "Your viewing"
    sql = str(seen["visible"].compile(dialect=postgresql.dialect()))
    assert "crm_inbound_enquiries.id =" in sql
    assert (seen["org"], seen["user"]) == ("org", "omar")


async def test_an_email_without_a_subject_gets_a_plain_one(monkeypatch):
    seen = {}

    async def send(db, *, payload, **kwargs):
        seen["subject"] = payload.subject
        return EmailSendBatchResponse(sent=0, failed=1, results=[])

    monkeypatch.setattr(email_pipeline, "send_emails", send)
    outcome = await connectors.BrevoEmailAdapter(Db(), **OWNER).dispatch(
        payload=SendMessage(lead_id=7, channel="email", body="Hello"), idempotency_key="a"
    )
    assert seen["subject"] == connectors.DEFAULT_SUBJECT
    assert outcome.status == "failed" and "Email not sent" in outcome.message


async def test_a_refused_email_reports_brevos_reason(monkeypatch):
    async def send(db, **kwargs):
        return EmailSendBatchResponse(
            sent=0,
            failed=1,
            results=[EmailSendResult(enquiry_id=7, email="x@y.z", ok=False, error="Marked do not contact")],
        )  # fmt: skip

    monkeypatch.setattr(email_pipeline, "send_emails", send)
    outcome = await connectors.BrevoEmailAdapter(Db(), **OWNER).dispatch(
        payload=EMAIL, idempotency_key="a"
    )
    assert outcome.status == "failed" and "Marked do not contact" in outcome.message


@pytest.mark.parametrize(
    ("sync", "status"), [("synced", "succeeded"), ("error", "failed"), ("pending", "failed")]
)
async def test_a_booking_lands_in_dubai_time_and_reports_googles_answer(monkeypatch, sync, status):
    seen = {}

    async def create(db, **kwargs):
        seen.update(kwargs)
        return {"google_sync_status": sync}

    monkeypatch.setattr(calendar_service, "create_event", create)
    outcome = await connectors.GoogleCalendarAdapter(Db(), **OWNER).dispatch(
        payload=VIEWING, idempotency_key="a"
    )
    # 07:00 UTC is 11:00 in Dubai.
    assert (str(seen["event_date"]), seen["event_time"], seen["end_time"]) == (
        "2026-11-20",
        "11:00",
        "12:00",
    )
    assert seen["kind"] == "viewing" and seen["lead_id"] == 7
    assert seen["location"] == "Marina Gate 2, Dubai Marina"
    assert outcome.status == status
    assert "20 Nov 2026 11:00 Dubai time" in outcome.message


# ── confirmation dispatches once, and only a ready connector ──


def _row(kind, payload):
    request = ActionProposalRequest(
        kind=kind, conversation_id=1, payload=payload, idempotency_key="key-12345678"
    )
    now = datetime.now(timezone.utc)
    return AssistantAction(
        id="action-1",
        **OWNER,
        conversation_id=1,
        kind=kind.value,
        status="awaiting_confirmation",
        idempotency_key="key-12345678",
        request_hash=service._request_hash(request, "omar", "org"),
        payload=payload,
        snapshot={"lead": "same"},
        preview={},
        created_at=now,
        expires_at=now + timedelta(minutes=15),
    )


@pytest.fixture
def confirming(monkeypatch):
    calls = {"dispatched": 0}

    def install(row, *, ready):
        async def load(db, user_id, organization_id, action_id):
            return row

        async def resources(db, request, user_id, organization_id):
            return {"contact": contact()}, {"lead": "same"}

        async def readiness(db, kind, payload, **kwargs):
            return ready, "delivery", None

        async def visible(db, r, user_id, organization_id):
            return SimpleNamespace(status=r.status, result=r.result)

        async def dispatch(db, *, user_id, organization_id, action_id, adapter):
            calls["dispatched"] += 1
            calls["adapter"] = type(adapter).__name__
            row.status = "succeeded"

        async def get_action(db, *, user_id, organization_id, action_id):
            return SimpleNamespace(status=row.status)

        monkeypatch.setattr(service, "_load", load)
        monkeypatch.setattr(service, "_resources", resources)
        monkeypatch.setattr(service.connectors, "readiness", readiness)
        monkeypatch.setattr(service, "_visible_response", visible)
        monkeypatch.setattr(service, "dispatch_confirmed", dispatch)
        monkeypatch.setattr(service, "get_action", get_action)
        return calls

    return install


async def test_a_confirmed_email_with_brevo_ready_is_sent_once(confirming):
    row = _row(ActionKind.SEND_MESSAGE, EMAIL.model_dump(mode="json", exclude_unset=True))
    calls = confirming(row, ready=True)
    db = Db()

    result = await service.confirm_action(db, **OWNER, action_id="action-1")

    assert calls["dispatched"] == 1 and calls["adapter"] == "BrevoEmailAdapter"
    assert result.status == "succeeded"
    outbox = next(r for r in db.added if type(r).__name__ == "AssistantOutbox")
    assert outbox.status == "queued"


async def test_a_confirmed_booking_with_google_connected_goes_to_google(confirming):
    row = _row(
        ActionKind.BOOK_EXTERNAL_VIEWING, VIEWING.model_dump(mode="json", exclude_unset=True)
    )
    calls = confirming(row, ready=True)
    await service.confirm_action(Db(), **OWNER, action_id="action-1")
    assert calls["dispatched"] == 1 and calls["adapter"] == "GoogleCalendarAdapter"


async def test_without_a_ready_connector_nothing_is_dispatched(confirming):
    row = _row(ActionKind.SEND_MESSAGE, EMAIL.model_dump(mode="json", exclude_unset=True))
    calls = confirming(row, ready=False)
    db = Db()

    result = await service.confirm_action(db, **OWNER, action_id="action-1")

    assert calls["dispatched"] == 0
    assert result.status == "not_connected"
    assert "Nothing was sent" in row.result["message"]
    outbox = next(r for r in db.added if type(r).__name__ == "AssistantOutbox")
    assert outbox.status == "not_connected"


async def test_a_second_confirmation_does_not_send_again(confirming):
    row = _row(ActionKind.SEND_MESSAGE, EMAIL.model_dump(mode="json", exclude_unset=True))
    calls = confirming(row, ready=True)
    await service.confirm_action(Db(), **OWNER, action_id="action-1")
    await service.confirm_action(Db(), **OWNER, action_id="action-1")
    assert calls["dispatched"] == 1
