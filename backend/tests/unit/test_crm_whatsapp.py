import hashlib
import hmac
import json

import httpx
import pytest

from app.crm.whatsapp import meta


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", "EAAG-test")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WABA_ID", "1029384756")
    monkeypatch.setattr(meta.settings, "WHATSAPP_GRAPH_API_VERSION", "v23.0")
    monkeypatch.setattr(meta.settings, "WHATSAPP_APP_SECRET", "app-secret")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", "verify-me")


def _sign(body: bytes, secret: str = "app-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Webhook trust ──


def test_only_a_body_signed_with_our_app_secret_is_trusted(configured):
    """Anyone can POST to the public webhook; only Meta knows the app secret. A forged or altered
    payload could otherwise inject customer messages or fake opt-outs."""
    body = b'{"entry":[]}'
    assert meta.verify_signature(body, _sign(body))
    assert not meta.verify_signature(body + b" ", _sign(body))
    assert not meta.verify_signature(body, _sign(body, "someone-else"))
    assert not meta.verify_signature(body, None)
    assert not meta.verify_signature(body, _sign(body).removeprefix("sha256="))


def test_nothing_is_trusted_while_the_app_secret_is_unset(configured, monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_APP_SECRET", None)
    body = b"{}"
    assert not meta.verify_signature(body, _sign(body, ""))


def test_webhook_registration_needs_our_verify_token(configured, monkeypatch):
    assert meta.verify_subscription("subscribe", "verify-me")
    assert not meta.verify_subscription("subscribe", "guess")
    assert not meta.verify_subscription("unsubscribe", "verify-me")
    monkeypatch.setattr(meta.settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", None)
    # An unset token must not match an empty one.
    assert not meta.verify_subscription("subscribe", "")


# ── Matching a lead's phone to the WhatsApp id Meta sends ──


def test_stored_phones_become_the_whatsapp_id_meta_uses():
    """A lead's reply must land on the lead whatever format the phone was typed in."""
    assert meta.wa_id_from_phone("+971 50 123 4567") == "971501234567"
    assert meta.wa_id_from_phone("00971501234567") == "971501234567"
    # UAE local mobile format, as agents type it.
    assert meta.wa_id_from_phone("050-123-4567") == "971501234567"
    assert meta.wa_id_from_phone("+44 7700 900123") == "447700900123"
    assert meta.wa_id_from_phone("12345") is None
    assert meta.wa_id_from_phone(None) is None


# ── Templates ──


def test_template_variables_are_counted_and_filled_in_order():
    body = "Hi {{1}}, this is {{2}} from Vitevue. Thanks for your enquiry about {{3}}."
    assert meta.variable_count(body) == 3
    assert meta.variable_count("No variables") == 0
    assert (
        meta.fill_template(body, ["Asha", "Sara", "the 2-bed in Marina Gate"])
        == "Hi Asha, this is Sara from Vitevue. Thanks for your enquiry about the 2-bed in Marina Gate."
    )
    # A missing value stays visible rather than silently disappearing.
    assert meta.fill_template("Hi {{1}} and {{2}}", ["Asha"]) == "Hi Asha and {{2}}"


async def test_template_send_carries_the_body_values_to_meta(configured):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["json"] = json.loads(request.content)
        return httpx.Response(200, json={"messages": [{"id": "wamid.ABC"}]})

    async with _client(handler) as client:
        wamid = await meta.send_template(
            client,
            phone_number_id="111222333",
            to="971501234567",
            name="agent_enquiry_follow_up",
            language="en",
            params=["Asha", "Sara"],
        )
    assert wamid == "wamid.ABC"
    # Sent from the agent's own number: that is what keeps each agent's chat separate.
    assert seen["url"] == "https://graph.facebook.com/v23.0/111222333/messages"
    assert seen["auth"] == "Bearer EAAG-test"
    assert seen["json"]["template"] == {
        "name": "agent_enquiry_follow_up",
        "language": {"code": "en"},
        "components": [
            {
                "type": "body",
                "parameters": [{"type": "text", "text": "Asha"}, {"type": "text", "text": "Sara"}],
            }
        ],
    }


async def test_a_refused_send_raises_with_metas_own_reason(configured):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "(#131047) Re-engagement message",
                    "error_data": {"details": "More than 24 hours have passed"},
                }
            },
        )

    async with _client(handler) as client:
        with pytest.raises(meta.MetaError, match="More than 24 hours have passed") as exc:
            await meta.send_text(client, phone_number_id="1", to="971501234567", body="Hi")
    assert exc.value.status == 400


async def test_nothing_is_sent_while_whatsapp_is_not_configured(monkeypatch):
    monkeypatch.setattr(meta.settings, "WHATSAPP_ACCESS_TOKEN", None)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("Meta must not be called without credentials")

    async with _client(handler) as client:
        with pytest.raises(meta.MetaError, match=meta.NOT_AVAILABLE):
            await meta.send_text(client, phone_number_id="1", to="971501234567", body="Hi")


async def test_templates_are_read_across_pages_and_unusable_states_are_dropped(configured):
    pages = {
        "first": {
            "data": [
                {
                    "name": "agent_enquiry_follow_up",
                    "language": "en",
                    "status": "APPROVED",
                    "category": "UTILITY",
                    "components": [{"type": "HEADER"}, {"type": "BODY", "text": "Hi {{1}}"}],
                },
                {"name": "old", "language": "en", "status": "DISABLED", "category": "MARKETING"},
            ],
            "paging": {"next": "https://graph.facebook.com/v23.0/next-page"},
        },
        "next": {
            "data": [
                {
                    "name": "new_listing_alert",
                    "language": "en",
                    "status": "PENDING",
                    "category": "MARKETING",
                    "components": [{"type": "BODY", "text": "New homes in {{1}}"}],
                }
            ]
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=pages["next" if "next-page" in str(request.url) else "first"]
        )

    async with _client(handler) as client:
        templates = await meta.list_templates(client)
    assert templates == [
        {
            "name": "agent_enquiry_follow_up",
            "language": "en",
            "category": "utility",
            "review": "approved",
            "body": "Hi {{1}}",
        },
        {
            "name": "new_listing_alert",
            "language": "en",
            "category": "marketing",
            "review": "pending",
            "body": "New homes in {{1}}",
        },
    ]


# ── Reading webhooks ──


def _webhook(value: dict) -> dict:
    return {"entry": [{"changes": [{"field": "messages", "value": value}]}]}


def test_incoming_messages_keep_the_number_that_received_them():
    """The receiving Phone Number ID decides which agent's chat a message joins."""
    messages, statuses = meta.parse_webhook(
        _webhook(
            {
                "metadata": {"phone_number_id": "111"},
                "contacts": [{"wa_id": "971501234567", "profile": {"name": "Asha"}}],
                "messages": [
                    {
                        "from": "971501234567",
                        "id": "wamid.in1",
                        "timestamp": "1762070400",
                        "type": "text",
                        "text": {"body": "Can we view it Saturday?"},
                    },
                    {
                        "from": "971501234567",
                        "id": "wamid.in2",
                        "timestamp": "1762070460",
                        "type": "button",
                        "button": {"text": "Stop promotions", "payload": "STOP"},
                    },
                    {"from": "971501234567", "id": "wamid.in3", "type": "image", "image": {}},
                ],
            }
        )
    )
    assert statuses == []
    assert [(m.phone_number_id, m.wa_id, m.wamid, m.body) for m in messages] == [
        ("111", "971501234567", "wamid.in1", "Can we view it Saturday?"),
        ("111", "971501234567", "wamid.in2", "Stop promotions"),
        ("111", "971501234567", "wamid.in3", "[image]"),
    ]
    assert messages[0].contact_name == "Asha"
    assert messages[0].at.timestamp() == 1762070400


def test_statuses_carry_metas_failure_reason_and_unknown_events_are_skipped():
    _, statuses = meta.parse_webhook(
        {
            "entry": [
                {
                    "changes": [
                        {
                            "field": "account_update",
                            "value": {"metadata": {"phone_number_id": "1"}},
                        },
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "111"},
                                "statuses": [
                                    {"id": "wamid.out1", "status": "read", "timestamp": "1"},
                                    {
                                        "id": "wamid.out2",
                                        "status": "failed",
                                        "timestamp": "2",
                                        "errors": [
                                            {
                                                "title": "Re-engagement message",
                                                "error_data": {"details": "Window closed"},
                                            }
                                        ],
                                    },
                                    {"id": "wamid.out3", "status": "warning"},
                                ],
                            },
                        },
                    ]
                }
            ]
        }
    )
    assert [(s.wamid, s.status, s.error) for s in statuses] == [
        ("wamid.out1", "read", None),
        ("wamid.out2", "failed", "Window closed"),
    ]


def test_customers_can_stop_and_start_again():
    """Opt-outs must be honoured promptly (Meta policy); START undoes a STOP."""
    assert meta.opt_change("STOP") == "out"
    assert meta.opt_change(" stop. ") == "out"
    assert meta.opt_change("Stop promotions") == "out"
    assert meta.opt_change("Unsubscribe") == "out"
    assert meta.opt_change("start") == "in"
    # Ordinary sentences containing the word are not opt-outs.
    assert meta.opt_change("Please don't stop sending listings") is None


def test_delivery_status_only_moves_forward():
    """Meta delivers statuses out of order; a late 'delivered' must not hide a 'read'."""
    assert meta.moves_forward("sent", "delivered")
    assert meta.moves_forward("read", "failed")
    assert not meta.moves_forward("read", "delivered")
    assert not meta.moves_forward("delivered", "delivered")
    assert meta.moves_forward(None, "sent")
