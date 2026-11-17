from datetime import date, datetime, timezone

import httpx
import pytest
from fastapi import HTTPException

from app.crm import brevo, email_pipeline, email_store
from app.crm.email_models import CrmEmailSend


def _send(**kw) -> CrmEmailSend:
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    kw.setdefault("organization_id", "org")
    return CrmEmailSend(
        id=7,
        to_email="a@example.com",
        subject="Hi",
        body="Hello",
        sent_by_user_id="u",
        status="sent",
        events=[],
        created_at=now,
        updated_at=now,
        **kw,
    )


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(brevo.settings, "BREVO_API_KEY", "xkeysib-test")
    monkeypatch.setattr(brevo.settings, "BREVO_SENDER_EMAIL", "leads@vitevue.ae")
    monkeypatch.setattr(brevo.settings, "BREVO_SENDER_NAME", "Vitevue")
    monkeypatch.setattr(brevo.settings, "BREVO_REPLY_TO", None)


def test_every_brevo_spelling_of_an_event_lands_on_one_name():
    assert brevo.canonical_event("hard_bounce") == "hardbounce"
    assert brevo.canonical_event("hardBounce") == "hardbounce"
    # The statistics API uses plurals.
    assert brevo.canonical_event("hardBounces") == "hardbounce"
    assert brevo.canonical_event("clicks") == "click"
    assert brevo.canonical_event("something_new") is None


def test_status_only_moves_forward_and_first_time_is_kept():
    send = _send()
    assert brevo.apply_event(send, "opened", 1761650000)
    opened_at = send.opened_at
    # A late `delivered` must not undo the open.
    assert brevo.apply_event(send, "delivered", 1761640000)
    assert send.status == "opened"
    assert send.delivered_at is not None
    assert brevo.apply_event(send, "opened", 1761660000)
    assert send.opened_at == opened_at


def test_a_repeated_event_is_ignored_so_webhook_and_sync_can_overlap():
    send = _send()
    assert brevo.apply_event(send, "click", "2026-10-28 10:00:00", "https://vitevue.ae")
    assert not brevo.apply_event(send, "clicks", "2026-10-28 10:00:00", "https://vitevue.ae")
    assert brevo.count_events(send) == (0, 1)


def test_proxy_opens_are_recorded_but_are_not_opens():
    send = _send()
    assert brevo.apply_event(send, "loadedByProxy", 1761650000)
    assert send.status == "sent" and send.opened_at is None
    assert brevo.count_events(send) == (0, 0)
    assert send.events[0]["event"] == "loadedbyproxy"


def test_bounce_outranks_engagement():
    send = _send()
    brevo.apply_event(send, "opened", 1)
    brevo.apply_event(send, "hard_bounce", 2)
    assert send.status == "bounced" and send.bounced_at is not None


def test_message_id_matches_with_or_without_brackets():
    assert set(brevo.message_id_variants("<abc@smtp>")) == {"<abc@smtp>", "abc@smtp"}


def test_template_fills_lead_tokens_and_leaves_others_visible():
    # Leads have no company: {{company}} must stay visible rather than vanish into "Hi  at".
    out = brevo.render_template(
        "Hi {{first_name}} ({{ email }}) at {{company}}", name="Sara Khan", email="s@x.ae"
    )
    assert out == "Hi Sara (s@x.ae) at {{company}}"


def test_text_body_becomes_escaped_paragraphs():
    assert brevo.text_to_html("Hi <b>\nthere\n\nBye") == "<p>Hi &lt;b&gt;<br>there</p><p>Bye</p>"


def test_button_and_links_become_clickable_so_brevo_can_track_them():
    out = brevo.text_to_html(
        "See [the shortlist](https://vv.ae/s?a=1&b=2) or https://vv.ae/x.\n\n"
        "[button: Book a viewing](https://vv.ae/book)"
    )
    assert '<a href="https://vv.ae/s?a=1&amp;b=2">the shortlist</a>' in out
    # The full stop after a bare URL is not part of the link.
    assert '<a href="https://vv.ae/x">https://vv.ae/x</a>.' in out
    assert '<a href="https://vv.ae/book" style="display:inline-block' in out
    assert ">Book a viewing</a>" in out


def test_only_web_links_are_made_clickable():
    # A javascript: or mailto: target stays as text, never a link.
    out = brevo.text_to_html("[click](javascript:alert(1)) [mail](mailto:a@b.c)")
    assert "<a " not in out


def test_plain_part_spells_out_where_a_button_goes():
    assert brevo.text_to_plain("[button: Book a viewing](https://vv.ae/book)") == (
        "Book a viewing: https://vv.ae/book"
    )


@pytest.mark.asyncio
async def test_send_tags_the_message_with_the_send_id(configured):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers["api-key"]
        seen["body"] = request.read()
        return httpx.Response(201, json={"messageId": "<m1@smtp>"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        message_id = await brevo.send_email(
            client, to="a@x.ae", to_name="A", subject="S", text="T", tag="42"
        )

    assert message_id == "<m1@smtp>"
    assert seen["key"] == "xkeysib-test"
    assert b'"tags":["42"]' in seen["body"]


@pytest.mark.asyncio
async def test_send_raises_brevos_own_message(configured):
    def handler(request):
        return httpx.Response(401, json={"code": "unauthorized", "message": "Key not found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(brevo.BrevoError, match="Key not found"):
            await brevo.send_email(
                client, to="a@x.ae", to_name=None, subject="S", text="T", tag="1"
            )


@pytest.mark.asyncio
async def test_send_without_config_never_calls_brevo(monkeypatch):
    monkeypatch.setattr(brevo.settings, "BREVO_API_KEY", None)
    with pytest.raises(brevo.BrevoError, match="not available"):
        await brevo.send_email(None, to="a@x.ae", to_name=None, subject="S", text="T", tag="1")


@pytest.mark.asyncio
async def test_event_pull_pages_until_a_short_page(configured, monkeypatch):
    monkeypatch.setattr(brevo, "EVENTS_PAGE", 2)
    offsets = []

    def handler(request):
        offset = int(request.url.params["offset"])
        offsets.append(offset)
        events = [{"event": "delivered"}] * (2 if offset == 0 else 1)
        return httpx.Response(200, json={"events": events})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [
            e
            async for e in brevo.fetch_events(
                client, start=date(2026, 10, 1), end=date(2026, 10, 2)
            )
        ]

    assert offsets == [0, 2] and len(events) == 3


@pytest.mark.asyncio
async def test_webhook_refuses_without_a_configured_secret(monkeypatch):
    monkeypatch.setattr(email_pipeline.settings, "BREVO_WEBHOOK_SECRET", None)
    with pytest.raises(HTTPException) as err:
        await email_pipeline.receive_webhook(secret="anything", payload={})
    assert err.value.status_code == 503


@pytest.mark.asyncio
async def test_webhook_refuses_a_wrong_secret(monkeypatch):
    monkeypatch.setattr(email_pipeline.settings, "BREVO_WEBHOOK_SECRET", "s3cret")
    with pytest.raises(HTTPException) as err:
        await email_pipeline.receive_webhook(secret="nope", payload={})
    assert err.value.status_code == 401


def test_template_types_are_ordered_and_all_five_means_every_type():
    write = email_pipeline.EmailTemplateWrite
    pick = email_pipeline._lead_types
    assert pick(write(name="n", subject="s", body="b", lead_types=["sell", "buy", "sell"])) == [
        "buy",
        "sell",
    ]
    # Ticking every type is the same template as ticking none: it is offered to all leads.
    every = ["buy", "rent", "sell", "let", "unknown"]
    assert pick(write(name="n", subject="s", body="b", lead_types=every)) == []


def test_reply_address_authenticates_the_send_only_on_our_inbound_domain(monkeypatch):
    monkeypatch.setattr(brevo.settings, "BREVO_INBOUND_DOMAIN", "reply.vitevue.ae")
    address = brevo.reply_address("42")
    assert address != "reply+42@reply.vitevue.ae"
    assert brevo.matches_reply_address(address.upper(), 42)
    assert not brevo.matches_reply_address(address, 43)
    assert not brevo.matches_reply_address("reply+42@reply.vitevue.ae", 42)
    assert not brevo.matches_reply_address(address.replace("reply.vitevue.ae", "gmail.com"), 42)
    assert not brevo.matches_reply_address("sara@reply.vitevue.ae", 42)


def test_without_inbound_domain_replies_go_to_the_configured_mailbox(monkeypatch):
    monkeypatch.setattr(brevo.settings, "BREVO_INBOUND_DOMAIN", None)
    monkeypatch.setattr(brevo.settings, "BREVO_REPLY_TO", "team@vitevue.ae")
    assert brevo.reply_address("42") == "team@vitevue.ae"


def test_inbound_item_prefers_the_reply_without_quoted_history():
    mail = brevo.parse_inbound(
        {
            "MessageId": "<abc@mail>",
            "InReplyTo": "<m1@smtp>",
            "From": {"Name": "Sara Khan", "Address": "Sara@Example.com"},
            "To": [{"Address": "reply+7@reply.vitevue.ae"}],
            "Cc": [{"Address": "agent@vitevue.ae"}],
            "Subject": "Re: New listings",
            "RawTextBody": "Yes please\n\n> On Monday you wrote...",
            "ExtractedMarkdownMessage": "Yes please",
            "Attachments": [{"Name": "passport.pdf"}],
            "SentAtDate": "Thu, 29 Oct 2026 10:02:31 +0400",
        }
    )
    assert mail.from_email == "sara@example.com"
    assert mail.body == "Yes please"
    assert mail.recipients == ["reply+7@reply.vitevue.ae", "agent@vitevue.ae"]
    assert mail.attachments == ["passport.pdf"]
    assert mail.received_at.utcoffset().total_seconds() == 4 * 3600


def test_inbound_item_without_a_sender_is_ignored():
    assert brevo.parse_inbound({"From": {"Name": "No address"}, "Subject": "x"}) is None


def test_a_reply_outranks_opens_and_clicks():
    send = _send()
    brevo.apply_event(send, "click", 1)
    assert brevo.apply_event(send, "replied", 2)
    assert send.status == "replied"
    # A late click after the reply does not move it back.
    brevo.apply_event(send, "click", 3)
    assert send.status == "replied"


@pytest.mark.asyncio
async def test_inbound_webhook_refuses_a_wrong_secret(monkeypatch):
    monkeypatch.setattr(email_pipeline.settings, "BREVO_WEBHOOK_SECRET", "s3cret")
    with pytest.raises(HTTPException) as err:
        await email_pipeline.receive_inbound(None, secret="nope", payload={"items": []})
    assert err.value.status_code == 401


@pytest.fixture
def store_file(tmp_path, monkeypatch):
    path = tmp_path / "crm_email_store.json"
    monkeypatch.setattr(email_store.settings, "CRM_EMAIL_STORE_PATH", str(path))
    return path


@pytest.mark.asyncio
async def test_store_starts_empty_and_survives_a_reload(store_file):
    assert (await email_store.read()).sends == []
    async with email_store.edit() as data:
        data.next_id("sends")
        data.next_id("sends")
    reloaded = await email_store.read()
    # Ids are never reused: they are Brevo tags that events come back with.
    assert reloaded.next_id("sends") == 3


@pytest.mark.asyncio
async def test_a_failed_edit_saves_nothing(store_file):
    with pytest.raises(RuntimeError):
        async with email_store.edit() as data:
            data.next_id("sends")
            raise RuntimeError("boom")
    assert not store_file.exists()


@pytest.mark.asyncio
async def test_test_send_is_recorded_with_brevos_message_id(store_file, configured):
    def handler(request):
        return httpx.Response(201, json={"messageId": "<m9@smtp>"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        send = await email_pipeline.send_to_address(
            organization_id="org",
            user_id="u",
            to_email=" Ashwin@Example.com ",
            to_name="Ashwin",
            subject="Hi {{first_name}}",
            body="Test",
            client=client,
        )
    assert (send.status, send.message_id, send.to_email) == (
        "sent",
        "<m9@smtp>",
        "ashwin@example.com",
    )
    assert send.subject == "Hi Ashwin"
    listed = await email_pipeline.list_sends(organization_id="org", status=None, limit=10, offset=0)
    assert [s.id for s in listed.items] == [send.id]


@pytest.mark.asyncio
async def test_a_brevo_refusal_is_kept_as_a_failed_send(store_file, configured):
    def handler(request):
        return httpx.Response(401, json={"message": "unrecognised IP address"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        send = await email_pipeline.send_to_address(
            organization_id="org",
            user_id="u",
            to_email="a@x.ae",
            to_name=None,
            subject="S",
            body="B",
            client=client,
        )
    assert send.status == "failed" and "unrecognised IP" in send.error


def test_events_stay_in_time_order_when_brevo_lists_newest_first():
    send = _send()
    brevo.apply_event(send, "opened", 300)
    brevo.apply_event(send, "delivered", 200)
    brevo.apply_event(send, "request", 100)
    # The Tracking tab's "Last event" is the last item: it must be the open, not the send.
    assert [e["event"] for e in send.events] == ["request", "delivered", "opened"]


@pytest.mark.asyncio
async def test_deleting_a_send_keeps_its_replies_unlinked(store_file):
    now = datetime(2026, 10, 28, tzinfo=timezone.utc)
    async with email_store.edit() as data:
        data.sends.append(_send())
        data.sends.append(_send(organization_id="other").model_copy(update={"id": 8}))
        data.inbound.append(
            email_pipeline.CrmEmailInbound(
                id=1,
                organization_id="org",
                send_id=7,
                from_email="a@x.ae",
                subject="Re",
                body="b",
                received_at=now,
                created_at=now,
            )
        )
    await email_pipeline.delete_send(organization_id="org", send_id=7)
    data = await email_store.read()
    assert [s.id for s in data.sends] == [8]
    assert data.inbound[0].send_id is None
    # Another organization's send cannot be deleted from here.
    with pytest.raises(HTTPException):
        await email_pipeline.delete_send(organization_id="org", send_id=8)
