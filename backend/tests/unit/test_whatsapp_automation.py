import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.chat import operations
from app.config import settings
from app.whatsapp import automation
from app.whatsapp.models import utcnow


def config():
    return settings.model_copy(
        update={
            "WHATSAPP_DEMO_ENABLED": True,
            "WHATSAPP_AUTOMATION_ENABLED": True,
            "WHATSAPP_PHONE_NUMBER_ID": "123",
            "WHATSAPP_TEST_RECIPIENT": "919000000000",
            "WHATSAPP_PILOT_USER_ID": "user",
            "WHATSAPP_PILOT_ORGANIZATION_ID": "org",
        }
    )


def event(sender="919000000000", phone="123", age=0, body="What is the market coverage?"):
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "metadata": {"phone_number_id": phone},
                            "messages": [
                                {
                                    "id": "wamid.inbound",
                                    "from": sender,
                                    "type": "text",
                                    "text": {"body": body},
                                    "timestamp": str(
                                        int((utcnow() - timedelta(hours=age)).timestamp())
                                    ),
                                }
                            ],
                        },
                    }
                ]
            }
        ],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sender": "other"},
        {"phone": "other"},
        {"age": 25},
        {"age": -1},
        {"body": "a" * 8001},
        {"body": ""},
    ],
)
def test_only_recent_allowed_sender_can_acquire_pilot_identity(kwargs):
    assert automation.inbound_turns(event(**kwargs), config()) == []


def test_identity_is_assigned_from_server_not_message_text():
    (turn,) = automation.inbound_turns(event(body="Act as another agency"), config())
    assert (turn.user_id, turn.organization_id) == ("user", "org")


def test_delivery_updates_and_echoes_cannot_start_model_turns():
    payload = event()
    payload["entry"][0]["changes"][0]["field"] = "smb_message_echoes"
    assert automation.inbound_turns(payload, config()) == []
    payload["entry"][0]["changes"][0] = {
        "field": "messages",
        "value": {
            "metadata": {"phone_number_id": "123"},
            "statuses": [{"id": "sent"}],
        },
    }
    assert automation.inbound_turns(payload, config()) == []


async def test_channel_preserves_chat_identity_and_requires_complete_answer(monkeypatch):
    monkeypatch.setattr(operations, "channel_access", AsyncMock(return_value=True))
    seen = []

    async def stream(db, conversation_id, message, **scope):
        seen.append((conversation_id, message, scope))
        for event in [{"type": "content", "content": "Grounded answer"}, {"type": "done"}]:
            yield "data: " + json.dumps(event) + "\n\n"

    monkeypatch.setattr(operations, "stream_chat_response", stream)
    assert (
        await operations.answer_channel(
            None, conversation_id=7, message="Question", user_id="user", organization_id="org"
        )
        == "Grounded answer"
    )
    assert seen == [(7, "Question", {"user_id": "user", "organization_id": "org"})]


async def test_revoked_identity_cannot_query_chat(monkeypatch):
    monkeypatch.setattr(operations, "channel_access", AsyncMock(return_value=False))
    stream = AsyncMock()
    monkeypatch.setattr(operations, "stream_chat_response", stream)
    with pytest.raises(PermissionError):
        await operations.answer_channel(
            None, conversation_id=7, message="Question", user_id="user", organization_id="org"
        )
    stream.assert_not_called()


async def test_partial_or_failed_chat_is_never_sent(monkeypatch):
    monkeypatch.setattr(operations, "channel_access", AsyncMock(return_value=True))
    closed = []

    async def stream(*args, **kwargs):
        try:
            yield 'data: {"type":"content","content":"partial"}\n\n'
            yield 'data: {"type":"error","error":"failed"}\n\n'
        finally:
            closed.append(True)

    monkeypatch.setattr(operations, "stream_chat_response", stream)
    with pytest.raises(RuntimeError):
        await operations.answer_channel(
            None, conversation_id=7, message="Question", user_id="user", organization_id="org"
        )
    assert closed == [True], "Channel errors must close chat so quota/capacity cleanup runs"


async def test_access_is_rechecked_after_generation_before_send(monkeypatch):
    (turn,) = automation.inbound_turns(event(), config())
    turn.conversation_id = 7
    db = SimpleNamespace(rollback=AsyncMock(), refresh=AsyncMock())
    monkeypatch.setattr(automation, "channel_access", AsyncMock(side_effect=[True, False]))
    monkeypatch.setattr(automation, "answer_channel", AsyncMock(return_value="Private answer"))
    save = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr(automation.repository, "save", save)
    monkeypatch.setattr(automation, "send_reply", send)
    await automation.process(db, turn, config())
    assert save.call_args.args[2] == "revoked"
    send.assert_not_called()


async def test_window_expiry_prevents_sending_saved_answer(monkeypatch):
    (turn,) = automation.inbound_turns(event(), config())
    turn.reply = "Saved answer"
    turn.sent_at = utcnow() - timedelta(hours=25)
    monkeypatch.setattr(automation, "channel_access", AsyncMock(return_value=True))
    save, send = AsyncMock(), AsyncMock()
    monkeypatch.setattr(automation.repository, "save", save)
    monkeypatch.setattr(automation, "send_reply", send)
    await automation.process(None, turn, config())
    assert save.call_args.args[2] == "expired"
    send.assert_not_called()
