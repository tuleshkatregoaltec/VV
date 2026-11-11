import json

import httpx
import pytest

from app.config import settings
from app.whatsapp import customer_automation as automation
from app.whatsapp import customer_timing as timing
from app.whatsapp.customer_models import (
    WhatsAppConnection,
    WhatsAppCustomerMessage,
    WhatsAppCustomerThread,
)
from app.whatsapp.models import utcnow
from app.whatsapp.token_crypto import encrypt_token


def config(**update):
    return settings.model_copy(
        update={
            "WHATSAPP_GRAPH_API_VERSION": "v25.0",
            "WHATSAPP_APP_SECRET": "secret",
            "WHATSAPP_HUMAN_TIMING_ENABLED": True,
            **update,
        }
    )


def fixtures(reply="Yep, it is 2 bed.", reason=None):
    connection = WhatsAppConnection(
        user_id="user",
        organization_id="org",
        phone_number_id="agent-number",
        account_id="agent-account",
        display_name="Kian",
        access_token_encrypted=encrypt_token("agent-token", config()),
    )
    thread = WhatsAppCustomerThread(connection_id=connection.id, sender="919000000000")
    message = WhatsAppCustomerMessage(
        id="wamid.inbound", thread_id=thread.id, sent_at=utcnow(), reply=reply, reason=reason
    )
    return connection, thread, message


@pytest.fixture
def graph(monkeypatch):
    calls = []
    behaviour = {"statuses": []}

    def respond(request):
        body = json.loads(request.content)
        calls.append((request, body))
        status = behaviour["statuses"].pop(0) if behaviour["statuses"] else 200
        if status != 200:
            return httpx.Response(status, json={"error": {"code": 131047}})
        if body.get("status") == "read":
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"messages": [{"id": f"out-{len(calls)}"}]})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        automation.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=httpx.MockTransport(respond), **kwargs),
    )
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(automation.asyncio, "sleep", fake_sleep)
    return calls, behaviour, sleeps


async def test_read_receipt_and_typing_indicator_use_metas_request_shape(graph):
    calls, _, _ = graph
    connection, _, message = fixtures()
    assert await automation.mark_read_typing(connection, message, config()) is True
    request, body = calls[0]
    assert request.url.path == "/v25.0/agent-number/messages"
    assert request.headers["authorization"] == "Bearer agent-token"
    assert body == {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": "wamid.inbound",
        "typing_indicator": {"type": "text"},
    }


async def test_typing_indicator_failure_is_ignored_and_never_logs_the_token(graph, caplog):
    _, behaviour, _ = graph
    behaviour["statuses"] = [500]
    connection, _, message = fixtures()
    assert await automation.mark_read_typing(connection, message, config()) is False
    connection.access_token_encrypted = None
    assert await automation.mark_read_typing(connection, message, config()) is False
    assert "agent-token" not in caplog.text


async def test_generated_reply_with_two_paragraphs_goes_out_as_two_texts(graph):
    calls, _, sleeps = graph
    connection, thread, message = fixtures("Yep, it is 2 bed.\n\nWant me to send details?")
    assert await automation.send_reply(connection, thread, message, config()) == "out-1"
    kinds = [("read" if body.get("status") else "text", body) for _, body in calls]
    assert [kind for kind, _ in kinds] == ["text", "read", "text"]
    assert kinds[0][1]["text"]["body"] == "Yep, it is 2 bed."
    assert kinds[0][1]["context"] == {"message_id": "wamid.inbound"}
    assert kinds[1][1]["typing_indicator"] == {"type": "text"}
    assert kinds[2][1]["text"]["body"] == "Want me to send details?"
    assert "context" not in kinds[2][1]
    assert len(sleeps) == 1 and timing.MIN_GAP <= sleeps[0] <= timing.MAX_GAP


async def test_failure_of_the_second_text_does_not_fail_or_repeat_the_first(graph):
    calls, behaviour, _ = graph
    behaviour["statuses"] = [200, 200, 400]
    connection, thread, message = fixtures("One.\n\nTwo.")
    assert await automation.send_reply(connection, thread, message, config()) == "out-1"
    assert [body.get("text", {}).get("body") for _, body in calls if "text" in body] == [
        "One.",
        "Two.",
    ]


async def test_failure_of_the_first_text_still_raises(graph):
    _, behaviour, _ = graph
    behaviour["statuses"] = [400]
    connection, thread, message = fixtures("One.\n\nTwo.")
    with pytest.raises(automation.MetaSendRejected):
        await automation.send_reply(connection, thread, message, config())


@pytest.mark.parametrize(
    "reason,timing_on", [("human_edited", True), (None, False)], ids=["agent-edit", "timing-off"]
)
async def test_agents_own_edit_and_untimed_sends_are_never_split(graph, reason, timing_on):
    calls, _, sleeps = graph
    connection, thread, message = fixtures("One.\n\nTwo.", reason=reason)
    await automation.send_reply(
        connection, thread, message, config(WHATSAPP_HUMAN_TIMING_ENABLED=timing_on)
    )
    assert len(calls) == 1 and calls[0][1]["text"]["body"] == "One.\n\nTwo."
    assert sleeps == []


async def test_typing_and_gap_sleeps_never_exceed_the_meta_indicator(graph):
    calls, _, sleeps = graph
    connection, thread, message = fixtures("A" * 300 + "\n\n" + "B" * 300)
    await automation.send_reply(connection, thread, message, config())
    assert sleeps and all(value < timing.INDICATOR_SECONDS for value in sleeps)
