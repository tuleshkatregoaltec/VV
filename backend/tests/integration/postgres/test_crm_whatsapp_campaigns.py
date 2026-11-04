import asyncio
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.crm.inbound_models import CrmInboundContact, CrmInboundEnquiry
from app.crm.whatsapp import campaigns, meta, service
from app.crm.whatsapp.models import (
    CrmWhatsAppCampaignRecipient,
    CrmWhatsAppNumber,
    CrmWhatsAppOptOut,
    WhatsAppCampaignCreate,
)

TEMPLATE = {
    "name": "new_listing_alert",
    "language": "en",
    "status": "APPROVED",
    "category": "MARKETING",
    "components": [{"type": "BODY", "text": "Hi {{1}}, new homes are available in {{2}}."}],
}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", "EAAG-test")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WABA_ID", "1029384756")
    monkeypatch.setattr(meta.settings, "WHATSAPP_GRAPH_API_VERSION", "v23.0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FakeMeta:
    """Meta's API: lists the template, accepts sends (or refuses chosen numbers), records them."""

    def __init__(self, refuse: set[str] | None = None, delay: float = 0):
        self.sent: list[dict] = []
        self.refuse = refuse or set()
        self.delay = delay

    async def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"data": [TEMPLATE]})
        body = json.loads(request.content)
        if self.delay:
            await asyncio.sleep(self.delay)
        if body["to"] in self.refuse:
            return httpx.Response(400, json={"error": {"message": "Message undeliverable"}})
        self.sent.append({"url": str(request.url), **body})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{uuid4().hex}"}]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


async def _campaign_number(session, org: str) -> CrmWhatsAppNumber:
    now = _now()
    number = CrmWhatsAppNumber(
        organization_id=org,
        phone_number_id=str(uuid4().int)[:15],
        display_number="+971 50 000 0003",
        label="Vitevue Properties",
        purpose="campaign",
        created_at=now,
        updated_at=now,
    )
    session.add(number)
    await session.commit()
    return number


async def _lead(session, org: str, name: str, phone: str | None, *, consent="provided", dnc=False):
    now = _now()
    contact = CrmInboundContact(
        organization_id=org,
        full_name=name,
        phone=phone,
        consent_status=consent,
        do_not_contact=dnc,
        created_at=now,
        updated_at=now,
    )
    session.add(contact)
    await session.flush()
    enquiry = CrmInboundEnquiry(
        organization_id=org,
        contact_id=contact.id,
        created_by_user_id="importer",
        intent="buy",
        enquiry_date=now,
        created_at=now,
        updated_at=now,
    )
    session.add(enquiry)
    await session.commit()
    return enquiry


def _payload(ids: list[int]) -> WhatsAppCampaignCreate:
    return WhatsAppCampaignCreate(
        name="Dubai Marina · new listings",
        template_name="new_listing_alert",
        language="en",
        params=[campaigns.FIRST_NAME, "Dubai Marina"],
        enquiry_ids=ids,
    )


async def test_the_audience_is_only_leads_who_agreed_to_promotions(pg_session):
    """Promotions go only to recorded opt-ins; opt-outs and do-not-contact are left out."""
    org = str(uuid4())
    asha = await _lead(pg_session, org, "Asha Rahman", "+971501111111")
    await _lead(pg_session, org, "No Consent", "+971502222222", consent="unknown")
    await _lead(pg_session, org, "Do Not Contact", "+971503333333", dnc=True)
    await _lead(pg_session, org, "Stopped", "+971504444444")
    await _lead(pg_session, org, "No Phone", None)
    pg_session.add(
        CrmWhatsAppOptOut(
            organization_id=org, wa_id="971504444444", reason="STOP", created_at=_now()
        )
    )
    await pg_session.commit()

    out = await campaigns.audience(pg_session, organization_id=org)

    assert [(i.id, i.wa_number) for i in out.items] == [(asha.id, "+971501111111")]
    assert (out.no_consent, out.opted_out, out.no_number) == (1, 2, 1)
    # Another organization's leads never appear.
    assert (await campaigns.audience(pg_session, organization_id=str(uuid4()))).items == []


async def test_a_campaign_sends_each_opted_in_lead_one_message_from_the_campaign_number(
    pg_session, configured
):
    org = str(uuid4())
    number = await _campaign_number(pg_session, org)
    asha = await _lead(pg_session, org, "ASHA RAHMAN", "+971501111111")
    omar = await _lead(pg_session, org, "Omar Khan", "050 222 2222")
    no_consent = await _lead(pg_session, org, "No Consent", "+971503333333", consent="unknown")
    meta_api = FakeMeta()

    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="manager",
        payload=_payload([asha.id, omar.id, no_consent.id]),
        client=meta_api.client(),
    )
    # The lead without consent is never added, even if a manager picks them.
    assert sorted(r.name for r in detail.recipients) == ["ASHA RAHMAN", "Omar Khan"]
    assert meta_api.sent == []  # nothing goes out until sending runs

    await campaigns.process_campaign(pg_session, detail.id, client=meta_api.client())

    assert len(meta_api.sent) == 2
    assert all(s["url"].endswith(f"/{number.phone_number_id}/messages") for s in meta_api.sent)
    first_values = {
        s["to"]: s["template"]["components"][0]["parameters"][0]["text"] for s in meta_api.sent
    }
    assert first_values == {"971501111111": "Asha", "971502222222": "Omar"}
    done = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    assert done.status == "completed"
    assert (done.counts.total, done.counts.sent, done.counts.pending) == (2, 2, 0)


async def test_someone_who_opts_out_before_their_turn_is_skipped(pg_session, configured):
    org = str(uuid4())
    await _campaign_number(pg_session, org)
    asha = await _lead(pg_session, org, "Asha", "+971501111111")
    meta_api = FakeMeta()
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload([asha.id]),
        client=meta_api.client(),
    )
    pg_session.add(
        CrmWhatsAppOptOut(
            organization_id=org, wa_id="971501111111", reason="STOP", created_at=_now()
        )
    )
    await pg_session.commit()

    await campaigns.process_campaign(pg_session, detail.id, client=meta_api.client())

    assert meta_api.sent == []
    done = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    assert (done.recipients[0].status, done.counts.skipped) == ("skipped", 1)


async def test_one_refused_send_does_not_stop_the_rest(pg_session, configured):
    org = str(uuid4())
    await _campaign_number(pg_session, org)
    asha = await _lead(pg_session, org, "Asha", "+971501111111")
    omar = await _lead(pg_session, org, "Omar", "+971502222222")
    meta_api = FakeMeta(refuse={"971501111111"})
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload([asha.id, omar.id]),
        client=meta_api.client(),
    )

    await campaigns.process_campaign(pg_session, detail.id, client=meta_api.client())

    done = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    by_name = {r.name: (r.status, r.error) for r in done.recipients}
    assert by_name == {"Asha": ("failed", "Message undeliverable"), "Omar": ("sent", None)}
    assert done.status == "completed"


async def test_two_servers_sending_at_once_never_message_anyone_twice(
    pg_session, postgres_test_url, configured
):
    """Production runs several API tasks; a resumed campaign may be picked up by two at once."""
    org = str(uuid4())
    await _campaign_number(pg_session, org)
    ids = [(await _lead(pg_session, org, f"Lead {i}", f"+97150{i:07d}")).id for i in range(60)]
    meta_api = FakeMeta(delay=0.005)
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload(ids),
        client=meta_api.client(),
    )

    engine = create_async_engine(postgres_test_url)
    try:
        async with (
            AsyncSession(engine, expire_on_commit=False) as one,
            AsyncSession(engine, expire_on_commit=False) as two,
        ):
            await asyncio.gather(
                campaigns.process_campaign(one, detail.id, client=meta_api.client()),
                campaigns.process_campaign(two, detail.id, client=meta_api.client()),
            )
    finally:
        await engine.dispose()

    recipients_sent_to = [s["to"] for s in meta_api.sent]
    assert len(recipients_sent_to) == 60
    assert len(set(recipients_sent_to)) == 60


async def test_resume_sends_the_rest_but_never_resends_someone_caught_mid_send(
    pg_session, configured
):
    """After a crash, a row left 'sending' may already have reached the customer: it is marked
    unknown for a person to check, not sent again."""
    org = str(uuid4())
    await _campaign_number(pg_session, org)
    asha = await _lead(pg_session, org, "Asha", "+971501111111")
    omar = await _lead(pg_session, org, "Omar", "+971502222222")
    meta_api = FakeMeta()
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload([asha.id, omar.id]),
        client=meta_api.client(),
    )
    caught = (
        await pg_session.exec(
            select(CrmWhatsAppCampaignRecipient).where(
                CrmWhatsAppCampaignRecipient.campaign_id == detail.id,
                CrmWhatsAppCampaignRecipient.name == "Asha",
            )
        )
    ).one()
    caught.status = "sending"
    caught.claimed_at = _now() - timedelta(hours=1)
    pg_session.add(caught)
    await pg_session.commit()

    await campaigns.resume_campaign(pg_session, organization_id=org, campaign_id=detail.id)
    await campaigns.process_campaign(pg_session, detail.id, client=meta_api.client())

    assert [s["to"] for s in meta_api.sent] == ["971502222222"]
    done = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    assert {r.name: r.status for r in done.recipients} == {"Asha": "unknown", "Omar": "sent"}
    assert done.status == "completed"


async def test_results_follow_delivery_and_replies_land_in_the_campaign_inbox(
    pg_session, configured
):
    org = str(uuid4())
    number = await _campaign_number(pg_session, org)
    asha = await _lead(pg_session, org, "Asha", "+971501111111")
    meta_api = FakeMeta()
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload([asha.id]),
        client=meta_api.client(),
    )
    await campaigns.process_campaign(pg_session, detail.id, client=meta_api.client())
    sent = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    wamid = (await service._messages(pg_session, number_id=number.id, wa_id="971501111111"))[
        0
    ].wamid

    def change(value: dict) -> dict:
        return {
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": number.phone_number_id},
                                **value,
                            },
                        }
                    ]
                }
            ]
        }

    await service.receive_webhook(
        pg_session,
        change({"statuses": [{"id": wamid, "status": "read", "timestamp": "9999999999"}]}),
    )
    await service.receive_webhook(
        pg_session,
        change(
            {
                "messages": [
                    {
                        "from": "971501111111",
                        "id": f"wamid.{uuid4().hex}",
                        "timestamp": str(int(_now().timestamp()) + 1),
                        "type": "text",
                        "text": {"body": "Is the JVC one still available?"},
                    }
                ]
            }
        ),
    )

    after = await campaigns.campaign_detail(pg_session, organization_id=org, campaign_id=detail.id)
    assert sent.counts.sent == 1
    assert (after.counts.read, after.counts.replies) == (1, 1)
    inbox = await campaigns.campaign_chats(pg_session, organization_id=org, user_id="m")
    assert [(c.wa_id, c.last_body, c.lead_id) for c in inbox] == [
        ("971501111111", "Is the JVC one still available?", asha.id)
    ]
    # The reply opened the 24-hour window, so the manager can answer from the campaign number.
    await campaigns.campaign_reply(
        pg_session,
        organization_id=org,
        user_id="m",
        wa_id="971501111111",
        body="Yes, it is!",
        client=meta_api.client(),
    )
    assert meta_api.sent[-1]["text"]["body"] == "Yes, it is!"
    assert meta_api.sent[-1]["url"].endswith(f"/{number.phone_number_id}/messages")


async def test_campaigns_need_a_campaign_number_and_stay_inside_the_organization(
    pg_session, configured
):
    org = str(uuid4())
    asha = await _lead(pg_session, org, "Asha", "+971501111111")
    with pytest.raises(HTTPException) as exc:
        await campaigns.create_campaign(
            pg_session,
            organization_id=org,
            user_id="m",
            payload=_payload([asha.id]),
            client=FakeMeta().client(),
        )
    assert exc.value.status_code == 409

    await _campaign_number(pg_session, org)
    detail = await campaigns.create_campaign(
        pg_session,
        organization_id=org,
        user_id="m",
        payload=_payload([asha.id]),
        client=FakeMeta().client(),
    )
    with pytest.raises(HTTPException) as exc:
        await campaigns.campaign_detail(
            pg_session, organization_id=str(uuid4()), campaign_id=detail.id
        )
    assert exc.value.status_code == 404
    # Another organization's lead ids are ignored, so nobody outside it can be messaged.
    other = await _lead(pg_session, str(uuid4()), "Outsider", "+971509999999")
    with pytest.raises(HTTPException) as exc:
        await campaigns.create_campaign(
            pg_session,
            organization_id=org,
            user_id="m",
            payload=_payload([other.id]),
            client=FakeMeta().client(),
        )
    assert exc.value.status_code == 422
