"""Failure-path regressions for retained prototypes; no provider calls or application data."""

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm import brevo, calendar_service, email_pipeline, email_store, router
from app.crm.calendar_models import CalendarEventMove, CrmCalendarConnection, CrmCalendarEvent
from app.crm.email_models import CrmEmailSend, EmailStoreData
from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry, CrmInboundImport
from app.crm.whatsapp import campaigns, meta, service
from app.crm.whatsapp.models import (
    CrmWhatsAppCampaign,
    CrmWhatsAppCampaignRecipient,
    CrmWhatsAppMessage,
    CrmWhatsAppNumber,
    CrmWhatsAppOptOut,
)

NOW = datetime(2026, 11, 17, tzinfo=timezone.utc)
DAY = date(2026, 11, 17)


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'connectors.db'}")
    tables = [
        model.__table__
        for model in (
            CrmInboundImport,
            CrmInboundContact,
            CrmInboundEnquiry,
            CrmCalendarConnection,
            CrmCalendarEvent,
            CrmWhatsAppNumber,
            CrmWhatsAppMessage,
            CrmWhatsAppOptOut,
            CrmWhatsAppCampaign,
            CrmWhatsAppCampaignRecipient,
        )
    ]
    async with engine.begin() as connection:
        await connection.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=tables))
    yield engine
    await engine.dispose()


@pytest.fixture
async def db(engine):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


def event(**values):
    return CrmCalendarEvent(
        **{
            "organization_id": "org",
            "user_id": "user",
            "title": "Unsynced local edit",
            "event_date": DAY,
            "event_time": "10:00",
            "event_end_date": DAY,
            "event_end_time": "12:00",
            "updated_at": NOW,
            **values,
        }
    )


@pytest.mark.parametrize("status", ["pending", "error"])
@pytest.mark.parametrize("cancelled", [False, True])
async def test_google_pull_never_erases_an_edit_waiting_to_be_pushed(
    db, monkeypatch, status, cancelled
):
    row = event(google_event_id="remote", google_sync_status=status)
    db.add(row)
    await db.commit()
    await calendar_service._store_google_event(
        db,
        event={
            "id": "remote",
            "status": "cancelled" if cancelled else "confirmed",
            "summary": "Old remote title",
            "start": {"dateTime": "2026-11-17T10:00:00+04:00"},
            "end": {"dateTime": "2026-11-17T12:00:00+04:00"},
        },
        user_id="user",
        organization_id="org",
    )
    await db.commit()
    assert (row.title, row.google_sync_status) == ("Unsynced local edit", status)
    calls = []

    async def google(method, url, **kw):
        calls.append((method, kw["body"]["summary"]))
        return {"id": "remote"}

    monkeypatch.setattr(calendar_service, "_google", google)
    connection = CrmCalendarConnection(organization_id="org", user_id="user")
    await calendar_service._sync_pending(db, connection=connection, token="offline")
    assert calls == [("PATCH", "Unsynced local edit")]
    assert row.google_sync_status == "synced"


@pytest.mark.parametrize("edit_before_retry", [False, True])
async def test_retry_after_google_accepts_but_loses_response_uses_one_provider_identity(
    db, monkeypatch, edit_before_retry
):
    row = event(google_sync_status="pending")
    db.add(row)
    await db.commit()
    provider = {}
    inserts = []

    async def google(method, url, **kw):
        if method == "GET":
            return provider[url.rsplit("/", 1)[1]]
        if method == "PATCH":
            identity = url.rsplit("/", 1)[1]
            provider[identity].update(kw["body"])
            return provider[identity]
        body = kw["body"]
        inserts.append(body.get("id"))
        identity = body.get("id") or f"server-generated-{len(inserts)}"
        if identity in provider:
            response = httpx.Response(409, request=httpx.Request(method, url))
            raise httpx.HTTPStatusError("exists", request=response.request, response=response)
        provider[identity] = {**body, "id": identity}
        raise httpx.ReadTimeout("Accepted; response lost")

    monkeypatch.setattr(calendar_service, "_google", google)
    connection = CrmCalendarConnection(organization_id="org", user_id="user")
    await calendar_service._sync_pending(db, connection=connection, token="offline")
    assert row.google_sync_status == "error"
    if edit_before_retry:
        row.title = "Edited again after timeout"
        await db.commit()
    # A new session models a retry after the original process exits.
    async with AsyncSession(db.bind, expire_on_commit=False) as retry:
        await calendar_service._sync_pending(retry, connection=connection, token="offline")
        saved = await retry.get(CrmCalendarEvent, row.id)
        assert saved.google_sync_status == "synced"
        assert saved.google_event_id == inserts[0]
    assert len(inserts) == 2 and inserts[0] == inserts[1]
    assert len(provider) == 1
    assert provider[inserts[0]]["summary"] == row.title
    assert set(inserts[0]) <= set("0123456789abcdefghijklmnopqrstuv")


@pytest.mark.parametrize(
    "start,end,new_start,new_end",
    [
        ("10:00", "12:00", "09:00", "11:00"),
        ("10:00", "12:00", "11:00", "13:00"),
        ("10:00", "10:15", "11:00", "11:15"),
    ],
)
async def test_moving_an_event_preserves_its_original_duration(
    db, monkeypatch, start, end, new_start, new_end
):
    row = event(event_time=start, event_end_time=end)
    db.add(row)
    await db.commit()
    monkeypatch.setattr(router, "_auth_ids", lambda _: ("user", "org"))
    result = await router.crm_move_calendar_event(
        row.id, CalendarEventMove(date=DAY, time=new_start), context=None, db=db
    )
    assert (result["time"], result["end_time"]) == (new_start, new_end)
    assert result["rescheduled_from"] == [{"date": DAY.isoformat(), "time": start}]


async def test_calendar_includes_in_progress_events_and_shifts_recurring_end_dates(db):
    db.add(
        event(title="Multi-day", event_time=None, all_day=True, event_end_date=date(2026, 11, 19))
    )
    db.add(
        event(
            title="Weekly",
            event_time=None,
            all_day=True,
            event_end_date=date(2026, 11, 19),
            repeat="weekly",
        )
    )
    await db.commit()
    first = await calendar_service.list_events(
        db, user_id="user", organization_id="org", start=date(2026, 11, 18), end=date(2026, 11, 18)
    )
    assert {e["title"] for e in first} == {"Multi-day", "Weekly"}
    second = await calendar_service.list_events(
        db, user_id="user", organization_id="org", start=date(2026, 11, 25), end=date(2026, 11, 25)
    )
    assert [(e["date"], e["end_date"]) for e in second] == [("2026-11-24", "2026-11-26")]


@pytest.fixture
def email_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(email_store.settings, "CRM_EMAIL_STORE_PATH", str(tmp_path / "email.json"))
    monkeypatch.setattr(brevo.settings, "BREVO_API_KEY", "offline")
    monkeypatch.setattr(brevo.settings, "BREVO_SENDER_EMAIL", "sender@example.com")
    monkeypatch.setattr(brevo.settings, "BREVO_WEBHOOK_SECRET", "offline-secret")
    monkeypatch.setattr(brevo.settings, "BREVO_INBOUND_DOMAIN", "reply.example.com")


async def send_email(client, org="org"):
    return await email_pipeline.send_to_address(
        organization_id=org,
        user_id="user",
        to_email="Customer@Example.com",
        to_name="Customer",
        subject="News",
        body="News",
        client=client,
    )


@pytest.mark.parametrize("response_status", [201, 400])
async def test_delivery_before_http_completion_keeps_the_newer_evidence(
    email_setup, response_status
):
    async def handler(request):
        tag = json.loads(request.content)["tags"][0]
        await email_pipeline.receive_webhook(
            secret="offline-secret", payload={"tag": tag, "event": "delivered", "ts": 100}
        )
        return httpx.Response(
            response_status, json={"messageId": "provider-id", "message": "Lost response"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        send = await send_email(client)
    assert send.status == "delivered"
    assert send.delivered_at is not None and send.error is None


@pytest.mark.parametrize("feedback", ["unsubscribed", "spam", "complaint"])
async def test_email_feedback_suppresses_address_after_send_is_deleted(email_setup, feedback):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"messageId": f"provider-{len(calls)}"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        original = await send_email(client)
        await email_pipeline.receive_webhook(
            secret="offline-secret", payload={"tag": str(original.id), "event": feedback, "ts": 100}
        )
        await email_pipeline.delete_send(organization_id="org", send_id=original.id)
        retry = await send_email(client)
        assert retry.status == "failed" and "suppressed" in retry.error
        # Consent in one organization cannot suppress another tenant's address.
        assert (await send_email(client, org="other")).status == "sent"
    assert len(calls) == 2
    assert (await email_store.read()).suppressed_addresses == {"org": ["customer@example.com"]}


@pytest.mark.parametrize("sender", ["attacker@example.com", "customer@example.com"])
@pytest.mark.parametrize("routing", ["legacy", "opaque", "thread"])
async def test_reply_routing_needs_unguessable_address_and_original_sender(
    email_setup, sender, routing
):
    original = CrmEmailSend(
        id=7,
        organization_id="victim",
        enquiry_id=9,
        to_email="customer@example.com",
        subject="News",
        body="Hello",
        sent_by_user_id="user",
        message_id="<original@smtp>",
        created_at=NOW,
        updated_at=NOW,
    )
    address = "reply+7@reply.example.com" if routing == "legacy" else brevo.reply_address("7")
    mail = brevo.parse_inbound(
        {
            "From": {"Address": sender},
            "To": [{"Address": address if routing != "thread" else "mail@example.com"}],
            "InReplyTo": "<original@smtp>" if routing == "thread" else None,
            "Subject": "Re: News",
            "RawTextBody": "Injected body",
        }
    )
    matched = email_pipeline._send_for_reply(EmailStoreData(sends=[original]), mail)
    assert (matched is original) == (sender == "customer@example.com" and routing != "legacy")


@pytest.mark.parametrize(
    "change",
    [
        "withdrawn",
        "do_not_contact",
        "phone_changed",
        "deleted_contact",
        "deleted_lead",
        "foreign_lead",
        "unchanged",
    ],
)
async def test_queued_campaign_rechecks_current_recipient_before_delivery(db, monkeypatch, change):
    contact = CrmInboundContact(
        organization_id="org",
        full_name="Customer",
        phone="+971501234567",
        consent_status="provided",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(contact)
    await db.flush()
    lead = CrmInboundEnquiry(
        organization_id="org",
        contact_id=contact.id,
        created_by_user_id="user",
        intent="buy",
        enquiry_date=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(lead)
    await db.flush()
    number = CrmWhatsAppNumber(
        organization_id="org",
        phone_number_id="provider",
        display_number="+971500000001",
        label="Campaign",
        purpose="campaign",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(number)
    await db.flush()
    campaign = CrmWhatsAppCampaign(
        organization_id="org",
        number_id=number.id,
        name="News",
        template_name="news",
        template_language="en",
        template_body="News",
        created_by_user_id="user",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(campaign)
    await db.flush()
    recipient = CrmWhatsAppCampaignRecipient(
        organization_id="org",
        campaign_id=campaign.id,
        enquiry_id=lead.id,
        wa_id="971501234567",
        name="Customer",
        status="sending",
        updated_at=NOW,
    )
    db.add(recipient)
    await db.commit()
    if change == "withdrawn":
        contact.consent_status = "withdrawn"
    elif change == "do_not_contact":
        contact.do_not_contact = True
    elif change == "phone_changed":
        contact.phone = "+971509999999"
    elif change == "deleted_contact":
        await db.delete(contact)
    elif change == "deleted_lead":
        await db.delete(lead)
    elif change == "foreign_lead":
        lead.organization_id = "other"
    await db.commit()
    deliver = AsyncMock(return_value="wamid.must-not-send")
    monkeypatch.setattr(meta, "send_template", deliver)
    await campaigns._send_one(db, None, campaign=campaign, number=number, r=recipient)
    messages = (await db.exec(select(CrmWhatsAppMessage))).all()
    if change == "unchanged":
        assert recipient.status == "sent" and recipient.error is None
        deliver.assert_awaited_once()
        assert len(messages) == 1 and messages[0].wa_id == recipient.wa_id
    else:
        assert recipient.status == "skipped" and recipient.error
        deliver.assert_not_awaited()
        assert not messages


@pytest.mark.parametrize(
    "component",
    [
        {"type": "HEADER", "format": "TEXT", "text": "Hello {{1}}"},
        {"type": "HEADER", "format": "IMAGE"},
        {"type": "BUTTONS", "buttons": [{"type": "URL", "url": "https://example.com/{{1}}"}]},
        {"type": "BUTTONS", "buttons": [{"type": "COPY_CODE"}]},
        {"type": "CAROUSEL"},
    ],
)
async def test_only_templates_the_sender_can_fulfil_are_offered(monkeypatch, component):
    monkeypatch.setattr(meta.settings, "WHATSAPP_WABA_ID", "offline")
    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", "offline")
    monkeypatch.setattr(meta.settings, "WHATSAPP_GRAPH_API_VERSION", "v23.0")
    body = {"type": "BODY", "text": "Hi {{1}}"}
    base = {"language": "en", "status": "APPROVED", "category": "MARKETING"}

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {**base, "name": "unsupported", "components": [body, component]},
                    {**base, "name": "body_only", "components": [body]},
                    {
                        **base,
                        "name": "static",
                        "components": [
                            body,
                            {"type": "HEADER", "format": "TEXT", "text": "News"},
                            {
                                "type": "BUTTONS",
                                "buttons": [{"type": "URL", "url": "https://example.com"}],
                            },
                        ],
                    },
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        templates = await meta.list_templates(client)
    assert [t["name"] for t in templates] == ["body_only", "static"]


def delivery(phone, status):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone},
                            "statuses": [
                                {"id": "wamid.test", "status": status, "timestamp": "100"}
                            ],
                        },
                    }
                ]
            }
        ]
    }


async def test_webhook_update_cannot_regress_a_stale_workers_status_or_cross_numbers(
    engine, db, monkeypatch
):
    number = CrmWhatsAppNumber(
        organization_id="org",
        phone_number_id="mine",
        display_number="+971500000001",
        label="Agent",
        purpose="agent",
        user_id="user",
        created_at=NOW,
        updated_at=NOW,
    )
    other = CrmWhatsAppNumber(
        organization_id="other",
        phone_number_id="theirs",
        display_number="+971500000002",
        label="Other",
        purpose="agent",
        user_id="other",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add_all([number, other])
    await db.flush()
    message = CrmWhatsAppMessage(
        organization_id="org",
        number_id=number.id,
        wa_id="971501234567",
        direction="out",
        body="Hello",
        wamid="wamid.test",
        status="sent",
        created_at=NOW,
        updated_at=NOW,
    )
    db.add(message)
    await db.commit()
    monkeypatch.setattr(service.live, "publish", AsyncMock())
    async with AsyncSession(engine, expire_on_commit=False) as stale:
        cached = await stale.get(CrmWhatsAppMessage, message.id)
        await stale.commit()
        assert (await service.receive_webhook(db, delivery("theirs", "failed")))["statuses"] == 0
        assert (await service.receive_webhook(db, delivery("mine", "read")))["statuses"] == 1
        assert cached.status == "sent"  # Independent worker still has an old identity-map value.
        assert (await service.receive_webhook(stale, delivery("mine", "delivered")))[
            "statuses"
        ] == 0
    await db.refresh(message)
    assert message.status == "read"


@pytest.mark.parametrize("remote_cancelled", [False, True])
async def test_old_google_snapshot_cannot_undo_a_push_completed_during_the_pull(
    db, remote_cancelled
):
    row = event(google_event_id="remote", google_sync_status="synced", updated_at=NOW)
    db.add(row)
    await db.commit()
    await calendar_service._store_google_event(
        db,
        event={
            "id": "remote",
            "status": "cancelled" if remote_cancelled else "confirmed",
            "summary": "Old remote title",
            "start": {"date": DAY.isoformat()},
        },
        user_id="user",
        organization_id="org",
        sync_started_at=NOW - timedelta(seconds=1),
    )
    await db.commit()
    assert (await db.get(CrmCalendarEvent, row.id)).title == "Unsynced local edit"


async def test_statistics_feedback_also_suppresses_later_sends(email_setup, monkeypatch):
    async def events(*args, **kwargs):
        yield {"tag": "1", "event": "unsubscribed", "date": NOW.isoformat()}

    monkeypatch.setattr(brevo, "fetch_events", events)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(201, json={"messageId": "provider-id"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        original = await send_email(client)
        await email_pipeline.sync_events(organization_id="org", client=client)
        await email_pipeline.delete_send(organization_id="org", send_id=original.id)
        assert (await send_email(client)).status == "failed"
    assert len(calls) == 1


@pytest.mark.parametrize(
    "sender,expected_org,expected_send",
    [
        ("attacker@example.com", "inbound", None),
        ("customer@example.com", "victim", 7),
    ],
)
async def test_inbound_webhook_keeps_unrelated_mail_out_of_a_victims_thread(
    db, email_setup, monkeypatch, sender, expected_org, expected_send
):
    monkeypatch.setattr(brevo.settings, "BREVO_INBOUND_ORGANIZATION_ID", "inbound")
    original = CrmEmailSend(
        id=7,
        organization_id="victim",
        enquiry_id=9,
        to_email="customer@example.com",
        subject="News",
        body="Hello",
        status="sent",
        sent_by_user_id="user",
        created_at=NOW,
        updated_at=NOW,
    )
    async with email_store.edit() as data:
        data.sends.append(original)
    assert (
        await email_pipeline.receive_inbound(
            db,
            secret="offline-secret",
            payload={
                "items": [
                    {
                        "From": {"Address": sender},
                        "To": [{"Address": brevo.reply_address("7")}],
                        "Subject": "Re: News",
                        "RawTextBody": "A reply",
                        "MessageId": "incoming-id",
                    }
                ]
            },
        )
        == 1
    )
    snapshot = await email_store.read()
    [mail] = snapshot.inbound
    assert (mail.organization_id, mail.send_id) == (expected_org, expected_send)
    assert snapshot.sends[0].status == ("replied" if expected_send else "sent")
