"""The assistant stream: the spec's SSE events, proposed actions saved on the reply, usage
recorded, no internal error text sent to the browser and no lead PII in the logs."""

import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from assistant_helpers import ORG_A, USER, FakeSession, make_deps, make_lead
from pydantic_ai.models.function import DeltaToolCall, FunctionModel
from pydantic_ai.models.test import TestModel

from app.crm.assistant import service
from app.crm.assistant.agent import assistant_agent
from app.crm.assistant.models import CrmAssistantAction, CrmAssistantMessage


def scripted(*turns):
    """A streaming model that plays one turn per request: text, or (tool name, args)."""
    played = iter(turns)

    async def stream(messages, info):
        turn = next(played)
        if isinstance(turn, Exception):
            raise turn
        if isinstance(turn, tuple):
            name, args = turn
            yield {0: DeltaToolCall(name=name, json_args=json.dumps(args))}
        else:
            yield turn

    return FunctionModel(stream_function=stream)


def decode(events):
    return [json.loads(event.removeprefix("data: ").strip()) for event in events]


@pytest.fixture
def stored(monkeypatch):
    """Conversation 3 exists for the caller; saved turns are recorded."""
    saved = []

    async def save(db, conversation_id, role, content, meta_data=None, **scope):
        saved.append((role, content, meta_data))

    monkeypatch.setattr(
        service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3, title=None))
    )
    monkeypatch.setattr(service, "list_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service.token_usage_service, "record_usage", AsyncMock())
    return saved


async def run(deps, text="hello"):
    return decode(
        [
            event
            async for event in service.stream_assistant_response(
                deps.db, conversation_id=3, user_message=text, deps=deps
            )
        ]
    )


async def test_missing_conversation_emits_only_error(monkeypatch):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=None))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    events = await run(make_deps(db=FakeSession()))
    assert events == [{"type": "error", "error": "Conversation not found"}]
    save.assert_not_awaited()


async def test_text_turn_emits_deltas_records_usage_then_done(stored):
    with assistant_agent.override(model=TestModel(call_tools=[], custom_output_text="No leads")):
        events = await run(make_deps(db=FakeSession()))

    assert "".join(e["content"] for e in events if e["type"] == "text-delta") == "No leads"
    assert events[-1] == {"type": "done"}
    service.token_usage_service.record_usage.assert_awaited_once()
    assert [turn[0] for turn in stored] == ["user", "assistant"]
    assert stored[1][1] == "No leads"


async def test_propose_tool_emits_action_proposed_and_saves_it_on_the_message(stored, fake_leads):
    fake_leads.add(make_lead(1))
    session = FakeSession()
    model = scripted(
        ("propose_add_note", {"lead_id": 1, "body": "Call Sunday"}),
        "Please confirm the note on the card.",
    )

    with assistant_agent.override(model=model):
        events = await run(make_deps(db=session))

    kinds = [event["type"] for event in events]
    assert kinds.index("tool-status") < kinds.index("action-proposed") < kinds.index("done")
    status = next(e for e in events if e["type"] == "tool-status")
    assert status == {
        "type": "tool-status",
        "tool": "propose_add_note",
        "label": "Preparing a change…",
    }
    proposed = next(e for e in events if e["type"] == "action-proposed")["action"]
    [row] = session.of_type(CrmAssistantAction)
    assert proposed["action_id"] == row.id
    assert row.conversation_id == 3
    assert stored[-1][2]["actions"][0]["action_id"] == row.id


async def test_provider_error_hides_details(stored, caplog):
    model = scripted(RuntimeError("upstream said: Ahmed +971501234567"))

    with caplog.at_level(logging.INFO), assistant_agent.override(model=model):
        events = await run(make_deps(db=FakeSession()))

    assert events[-1] == {"type": "error", "error": "Something went wrong"}
    assert "+971501234567" not in caplog.text


async def test_no_pii_in_logs(stored, fake_leads, caplog):
    fake_leads.add(make_lead(1, notes=["Lives in villa 12"]))
    model = scripted(("get_lead", {"lead_id": 1}), "Here is the lead.")

    with caplog.at_level(logging.DEBUG), assistant_agent.override(model=model):
        await run(make_deps(db=FakeSession()), text="Tell me about Ahmed Khan")

    for secret in ("+971501234567", "ahmed@example.com", "Ahmed Khan", "villa 12"):
        assert secret not in caplog.text
    assert "get_lead" in caplog.text


async def test_messages_report_current_action_status(monkeypatch):
    now = datetime.now(timezone.utc)
    message = CrmAssistantMessage(
        id=1,
        conversation_id=3,
        role="assistant",
        content="Confirm below",
        meta_data={
            "actions": [
                {"action_id": "a1", "status": "pending"},
                {"action_id": "a2", "status": "pending"},
                {"action_id": "a3", "status": "pending"},
            ]
        },
        created_at=now,
    )
    rows = [
        SimpleNamespace(id="a1", status="confirmed", expires_at=now + timedelta(minutes=5)),
        SimpleNamespace(id="a2", status="pending", expires_at=now - timedelta(minutes=1)),
        SimpleNamespace(id="a3", status="pending", expires_at=now + timedelta(minutes=5)),
    ]
    monkeypatch.setattr(service, "list_messages", AsyncMock(return_value=[message]))
    lookup = AsyncMock(return_value=rows)
    monkeypatch.setattr(service.repository, "get_actions_by_ids", lookup)

    [response] = await service.get_messages_with_action_status(None, 3, USER, ORG_A)

    assert [a["status"] for a in response.meta_data["actions"]] == [
        "confirmed",
        "expired",
        "pending",
    ]
    assert lookup.await_args.args[2:] == (USER, ORG_A)


async def test_messages_from_the_earlier_assistant_still_load(monkeypatch):
    """Rows the earlier assistant stored hold a JSON list (its sources) in this column."""
    from app.crm.assistant.agent import history_to_model_messages

    old = CrmAssistantMessage(
        id=1,
        conversation_id=3,
        role="assistant",
        content="Old answer",
        meta_data=[{"title": "a source"}],
        created_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(service, "list_messages", AsyncMock(return_value=[old]))
    monkeypatch.setattr(service.repository, "get_actions_by_ids", AsyncMock(return_value=[]))

    [response] = await service.get_messages_with_action_status(None, 3, USER, ORG_A)
    assert response.content == "Old answer"
    assert response.meta_data == {}
    assert len(history_to_model_messages([old])) == 1
