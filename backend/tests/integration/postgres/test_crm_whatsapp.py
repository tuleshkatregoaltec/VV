from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.crm.whatsapp import live, meta, service
from app.crm.whatsapp.models import (
    CrmWhatsAppMessage,
    CrmWhatsAppNumber,
    CrmWhatsAppOptOut,
    WhatsAppNumberWrite,
    WhatsAppTemplateSend,
)
from app.organization.models import Organization, OrganizationMembership

CUSTOMER = "971501234567"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", "EAAG-test")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WABA_ID", "1029384756")
    monkeypatch.setattr(meta.settings, "WHATSAPP_GRAPH_API_VERSION", "v23.0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _number(session, org: str, user: str | None, purpose: str = "agent") -> CrmWhatsAppNumber:
    now = _now()
    number = CrmWhatsAppNumber(
        organization_id=org,
        phone_number_id=str(uuid4().int)[:15],
        display_number="+971 50 000 0001",
        label="Vitevue · Sara",
        purpose=purpose,
        user_id=user,
        created_at=now,
        updated_at=now,
    )
    session.add(number)
    await session.commit()
    return number


async def _lead(
    session, org: str, phone: str, *, consent: str = "unknown", assigned: str | None = None
):
    now = _now()
    contact = CrmInboundContact(
        organization_id=org,
        full_name="Asha Rahman",
        phone=phone,
        consent_status=consent,
        created_at=now,
        updated_at=now,
    )
    session.add(contact)
    await session.flush()
    enquiry = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id="importer",
        assigned_user_id=assigned,
        intent="buy",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    session.add(enquiry)
    await session.commit()
    return enquiry


def _inbound(number: CrmWhatsAppNumber, wamid: str, body: str, at: datetime | None = None) -> dict:
    at = at or _now()
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": number.phone_number_id},
                            "contacts": [{"wa_id": CUSTOMER, "profile": {"name": "Asha"}}],
                            "messages": [
                                {
                                    "from": CUSTOMER,
                                    "id": wamid,
                                    "timestamp": str(int(at.timestamp())),
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ]
            }
        ]
    }


def _status(number: CrmWhatsAppNumber, wamid: str, status: str, ts: int) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": number.phone_number_id},
                            "statuses": [{"id": wamid, "status": status, "timestamp": str(ts)}],
                        },
                    }
                ]
            }
        ]
    }


def _meta(templates: list[dict] | None = None, sent: list | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": templates or []})
        if sent is not None:
            sent.append(request)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.out.{uuid4().hex}"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_repeated_webhook_stores_the_message_once(pg_session):
    """Meta redelivers webhooks; the agent must not see the same message twice."""
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    payload = _inbound(number, f"wamid.{uuid4().hex}", "Can we view it Saturday?")

    assert await service.receive_webhook(pg_session, payload) == {"messages": 1, "statuses": 0}
    assert await service.receive_webhook(pg_session, payload) == {"messages": 0, "statuses": 0}

    chats = await service.list_chats(pg_session, organization_id=org, user_id=sara)
    assert [(c.wa_id, c.last_body, c.unread, c.contact_name) for c in chats] == [
        (CUSTOMER, "Can we view it Saturday?", 1, "Asha")
    ]


async def test_a_stored_message_tells_open_screens_which_chat_changed(pg_session, monkeypatch):
    """Live updates go to the number's organization, naming the agent, and only for news: a
    repeated delivery from Meta must not make every screen refetch."""
    published: list[tuple[str, set]] = []

    async def record(organization_id, changes):
        published.append((organization_id, changes))

    monkeypatch.setattr(live, "publish", record)
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    payload = _inbound(number, f"wamid.{uuid4().hex}", "Still available?")

    await service.receive_webhook(pg_session, payload)
    await service.receive_webhook(pg_session, payload)

    assert published == [(org, {live.ChatChange(wa_id=CUSTOMER, purpose="agent", user_id=sara)})]


async def test_each_agent_sees_only_the_chats_on_their_own_number(pg_session):
    """The customer has one chat per agent; Sara must not read or answer Omar's."""
    org, sara, omar = str(uuid4()), str(uuid4()), str(uuid4())
    sara_number = await _number(pg_session, org, sara)
    omar_number = await _number(pg_session, org, omar)
    await service.receive_webhook(
        pg_session, _inbound(sara_number, f"wamid.{uuid4().hex}", "To Sara")
    )
    await service.receive_webhook(
        pg_session, _inbound(omar_number, f"wamid.{uuid4().hex}", "To Omar")
    )

    sara_chat = await service.chat_thread(
        pg_session, organization_id=org, user_id=sara, wa_id=CUSTOMER
    )
    omar_chat = await service.chat_thread(
        pg_session, organization_id=org, user_id=omar, wa_id=CUSTOMER
    )
    assert [m.body for m in sara_chat.messages] == ["To Sara"]
    assert [m.body for m in omar_chat.messages] == ["To Omar"]
    # Another organization's agent with the same user id sees nothing.
    assert await service.list_chats(pg_session, organization_id=str(uuid4()), user_id=sara) == []


async def test_a_webhook_for_a_number_not_in_the_crm_is_ignored(pg_session):
    stranger = CrmWhatsAppNumber(
        organization_id="x",
        phone_number_id="999000999000",
        display_number="",
        label="",
        created_at=_now(),
        updated_at=_now(),
    )
    payload = _inbound(stranger, f"wamid.{uuid4().hex}", "Hello")
    assert await service.receive_webhook(pg_session, payload) == {"messages": 0, "statuses": 0}


async def test_stop_records_an_opt_out_and_start_lifts_it(pg_session, configured):
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)

    await service.receive_webhook(pg_session, _inbound(number, f"wamid.{uuid4().hex}", "STOP"))
    assert await pg_session.get(CrmWhatsAppOptOut, (org, CUSTOMER)) is not None
    thread = await service.chat_thread(
        pg_session, organization_id=org, user_id=sara, wa_id=CUSTOMER
    )
    assert thread.opted_out

    # Even inside the 24-hour window, nothing more goes to them.
    with pytest.raises(HTTPException) as exc:
        await service.reply_to_chat(
            pg_session,
            organization_id=org,
            user_id=sara,
            wa_id=CUSTOMER,
            body="Sure",
            client=_meta(),
        )
    assert exc.value.status_code == 409

    await service.receive_webhook(pg_session, _inbound(number, f"wamid.{uuid4().hex}", "start"))
    pg_session.expire_all()
    assert await pg_session.get(CrmWhatsAppOptOut, (org, CUSTOMER)) is None


async def test_free_form_replies_only_inside_the_24_hour_window(pg_session, configured):
    """Outside the window Meta refuses free-form messages; the CRM says so before trying."""
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    old = _now() - timedelta(hours=25)
    await service.receive_webhook(
        pg_session, _inbound(number, f"wamid.{uuid4().hex}", "Hi", at=old)
    )
    sent: list = []

    with pytest.raises(HTTPException) as exc:
        await service.reply_to_chat(
            pg_session,
            organization_id=org,
            user_id=sara,
            wa_id=CUSTOMER,
            body="Hello",
            client=_meta(sent=sent),
        )
    assert exc.value.status_code == 409
    assert sent == []

    await service.receive_webhook(
        pg_session, _inbound(number, f"wamid.{uuid4().hex}", "Still there?")
    )
    await service.reply_to_chat(
        pg_session,
        organization_id=org,
        user_id=sara,
        wa_id=CUSTOMER,
        body="Yes!",
        client=_meta(sent=sent),
    )
    # Sent from Sara's own number.
    assert str(sent[0].url).endswith(f"/{number.phone_number_id}/messages")
    thread = await service.chat_thread(
        pg_session, organization_id=org, user_id=sara, wa_id=CUSTOMER
    )
    assert [(m.direction, m.body, m.status) for m in thread.messages][-1] == ("out", "Yes!", "sent")


async def test_an_agent_without_a_number_cannot_send(pg_session, configured):
    org = str(uuid4())
    with pytest.raises(HTTPException) as exc:
        await service.reply_to_chat(
            pg_session,
            organization_id=org,
            user_id=str(uuid4()),
            wa_id=CUSTOMER,
            body="Hi",
            client=_meta(),
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == service.NO_NUMBER


async def test_a_template_starts_the_chat_with_the_leads_first_name(pg_session, configured):
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    lead = await _lead(pg_session, org, "050 123 4567", assigned=sara)
    sent: list = []
    templates = [
        {
            "name": "agent_enquiry_follow_up",
            "language": "en",
            "status": "APPROVED",
            "category": "UTILITY",
            "components": [{"type": "BODY", "text": "Hi {{1}}, thanks for your enquiry."}],
        }
    ]

    await service.template_to_lead(
        pg_session,
        organization_id=org,
        user_id=sara,
        enquiry_id=lead.id,
        payload=WhatsAppTemplateSend(name="agent_enquiry_follow_up", language="en"),
        client=_meta(templates, sent),
    )

    stored = (
        await pg_session.exec(
            select(CrmWhatsAppMessage).where(CrmWhatsAppMessage.number_id == number.id)
        )
    ).one()
    assert (stored.wa_id, stored.body, stored.template_name) == (
        CUSTOMER,
        "Hi Asha, thanks for your enquiry.",
        "agent_enquiry_follow_up",
    )
    # The lead's reply to that number now shows on the lead and in Sara's chat list.
    chats = await service.list_chats(pg_session, organization_id=org, user_id=sara)
    assert (chats[0].lead_id, chats[0].lead_name) == (lead.id, "Asha Rahman")


async def test_marketing_templates_need_recorded_consent(pg_session, configured):
    """Promotions go only to contacts who agreed to them (Meta policy, and the proposal)."""
    org, sara = str(uuid4()), str(uuid4())
    await _number(pg_session, org, sara)
    lead = await _lead(pg_session, org, "+971501234567")
    templates = [
        {
            "name": "new_listing_alert",
            "language": "en",
            "status": "APPROVED",
            "category": "MARKETING",
            "components": [{"type": "BODY", "text": "Hi {{1}}, new homes are available."}],
        }
    ]
    sent: list = []
    payload = WhatsAppTemplateSend(name="new_listing_alert", language="en")

    with pytest.raises(HTTPException) as exc:
        await service.template_to_lead(
            pg_session,
            organization_id=org,
            user_id=sara,
            enquiry_id=lead.id,
            payload=payload,
            client=_meta(templates, sent),
        )
    assert exc.value.status_code == 409
    assert sent == []


async def test_a_refused_send_stays_on_the_thread_with_metas_reason(pg_session, configured):
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    await service.receive_webhook(pg_session, _inbound(number, f"wamid.{uuid4().hex}", "Hi"))

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "Recipient phone number not in allowed list"}}
        )

    with pytest.raises(HTTPException) as exc:
        await service.reply_to_chat(
            pg_session,
            organization_id=org,
            user_id=sara,
            wa_id=CUSTOMER,
            body="Hello",
            client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
        )
    assert exc.value.status_code == 502
    thread = await service.chat_thread(
        pg_session, organization_id=org, user_id=sara, wa_id=CUSTOMER
    )
    last = thread.messages[-1]
    assert (last.status, last.error) == ("failed", "Recipient phone number not in allowed list")


async def test_delivery_statuses_only_move_forward(pg_session, configured):
    org, sara = str(uuid4()), str(uuid4())
    number = await _number(pg_session, org, sara)
    await service.receive_webhook(pg_session, _inbound(number, f"wamid.{uuid4().hex}", "Hi"))
    await service.reply_to_chat(
        pg_session, organization_id=org, user_id=sara, wa_id=CUSTOMER, body="Hello", client=_meta()
    )
    out = (
        await pg_session.exec(
            select(CrmWhatsAppMessage).where(
                CrmWhatsAppMessage.number_id == number.id, CrmWhatsAppMessage.direction == "out"
            )
        )
    ).one()

    await service.receive_webhook(pg_session, _status(number, out.wamid, "read", 200))
    await service.receive_webhook(pg_session, _status(number, out.wamid, "delivered", 100))
    await pg_session.refresh(out)
    assert out.status == "read"


async def test_numbers_are_assigned_to_members_one_active_number_each(pg_session):
    org_id = str(uuid4())
    pg_session.add(Organization(id=org_id, name="Vitevue"))
    await pg_session.flush()
    sara = str(uuid4())
    pg_session.add(OrganizationMembership(organization_id=org_id, user_id=sara, role="member"))
    await pg_session.commit()

    def number(purpose="agent", user=sara, active=True):
        return WhatsAppNumberWrite(
            display_number="+971 50 000 0001",
            label="Sara",
            purpose=purpose,
            user_id=user,
            active=active,
        )

    await service.save_number(
        pg_session, organization_id=org_id, phone_number_id="1110001", payload=number()
    )

    # A second active number for the same agent would split her chats.
    with pytest.raises(HTTPException) as exc:
        await service.save_number(
            pg_session, organization_id=org_id, phone_number_id="1110002", payload=number()
        )
    assert exc.value.status_code == 409

    # Someone outside the organization cannot be given a number.
    with pytest.raises(HTTPException) as exc:
        await service.save_number(
            pg_session,
            organization_id=org_id,
            phone_number_id="1110003",
            payload=number(user=str(uuid4())),
        )
    assert exc.value.status_code == 422

    # Another organization cannot take over a registered number.
    with pytest.raises(HTTPException) as exc:
        await service.save_number(
            pg_session,
            organization_id=str(uuid4()),
            phone_number_id="1110001",
            payload=number(purpose="campaign", user=None),
        )
    assert exc.value.status_code == 409

    await service.save_number(
        pg_session,
        organization_id=org_id,
        phone_number_id="1110004",
        payload=number(purpose="campaign", user=None),
    )
    with pytest.raises(HTTPException) as exc:
        await service.save_number(
            pg_session,
            organization_id=org_id,
            phone_number_id="1110005",
            payload=number(purpose="campaign", user=None),
        )
    assert exc.value.status_code == 409


async def test_status_tells_an_agent_without_a_number_apart_from_whatsapp_being_off(
    pg_session, configured, monkeypatch
):
    """The screen must say "ask for a number", not "not connected", when only the number is missing."""
    org, sara = str(uuid4()), str(uuid4())
    without = await service.whatsapp_status(pg_session, organization_id=org, user_id=sara)
    assert (without.configured, without.connected) == (False, True)

    await _number(pg_session, org, sara)
    assert (await service.whatsapp_status(pg_session, organization_id=org, user_id=sara)).configured

    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", None)
    off = await service.whatsapp_status(pg_session, organization_id=org, user_id=sara)
    assert (off.configured, off.connected) == (False, False)
