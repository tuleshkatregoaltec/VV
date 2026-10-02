import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.toolsets.function import FunctionToolset

from app.chat import service


def decode(events):
    return [json.loads(event.removeprefix("data: ").strip()) for event in events]


@pytest.fixture
def turn(monkeypatch):
    db = AsyncMock()
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "_authorize_tools", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    claim = AsyncMock(return_value=("claimed", SimpleNamespace(id=1)))
    finish = AsyncMock()
    monkeypatch.setattr(service.repository, "claim_turn", claim)
    monkeypatch.setattr(service.repository, "finish_turn", finish)

    @asynccontextmanager
    async def scope(*args, **kwargs):
        yield FunctionToolset()

    monkeypatch.setattr(service, "market_mcp", scope)
    monkeypatch.setattr(service, "ai_execution", scope)
    return db, claim, finish


async def test_missing_conversation_emits_only_error(monkeypatch):
    lookup = AsyncMock(return_value=None)
    claim = AsyncMock()
    monkeypatch.setattr(service, "get_conversation", lookup)
    monkeypatch.setattr(service.repository, "claim_turn", claim)
    events = [
        event async for event in service.stream_chat_response(None, 3, "hello", "other", "org")
    ]
    assert decode(events) == [{"type": "error", "error": "Conversation not found"}]
    claim.assert_not_awaited()


async def test_provider_failure_preserves_failed_status_without_leaking_error(turn, monkeypatch):
    db, _, finish = turn

    @asynccontextmanager
    async def fail(*args, **kwargs):
        raise RuntimeError("provider secret: private prompt")
        yield

    monkeypatch.setattr(service, "agent", SimpleNamespace(iter=fail))
    events = decode(
        [event async for event in service.stream_chat_response(db, 3, "hello", "owner", "org")]
    )
    assert [event["type"] for event in events] == ["thinking", "error"]
    assert "secret" not in json.dumps(events)
    assert finish.await_args.args[5] == "failed"


async def test_text_turn_persists_answer_and_prompt_version_before_done(turn):
    db, claim, finish = turn
    with service.agent.override(model=TestModel(call_tools=[], custom_output_text="Known answer")):
        events = decode(
            [
                event
                async for event in service.stream_chat_response(
                    db, 3, "hello", "owner", "org", request_id="stable-id"
                )
            ]
        )
    assert events[-1] == {"type": "done"}
    assert (
        "".join(item["content"] for item in events if item["type"] == "content") == "Known answer"
    )
    assert claim.await_args.args[-2:] == ("stable-id", "hello")
    assert finish.await_args.args[5:7] == ("complete", "Known answer")
    assert finish.await_args.args[7]["prompt_version"] == service.CHAT_PROMPT_VERSION
    assert db.commit.await_count == 2


async def test_completed_retry_replays_without_model_or_usage(turn, monkeypatch):
    db, claim, finish = turn
    claim.return_value = ("complete", SimpleNamespace(id=1))
    monkeypatch.setattr(
        service.repository,
        "replay_turn",
        AsyncMock(return_value=SimpleNamespace(content="Saved answer", meta_data={})),
    )
    model = AsyncMock()
    monkeypatch.setattr(service, "market_mcp", model)
    events = decode(
        [event async for event in service.stream_chat_response(db, 3, "hello", "owner", "org")]
    )
    assert events == [
        {"type": "thinking"},
        {"type": "content", "content": "Saved answer"},
        {"type": "done"},
    ]
    model.assert_not_called()
    finish.assert_not_awaited()


async def test_disconnect_marks_cancelled_and_releases_resources(turn):
    db, _, finish = turn
    stream = service.stream_chat_response(db, 3, "hello", "owner", "org")
    assert decode([await anext(stream)]) == [{"type": "thinking"}]
    await stream.aclose()
    assert finish.await_args.args[5] == "cancelled"
    assert db.commit.await_count == 2


async def test_unbound_building_clarifies_without_provider_or_invented_facts(turn, monkeypatch):
    db, _, finish = turn
    model = AsyncMock()
    monkeypatch.setattr(service, "market_mcp", model)
    events = decode(
        [
            event
            async for event in service.stream_chat_response(
                db, 3, "Appraise [building], JLT", "owner", "org"
            )
        ]
    )
    assert events[-1]["type"] == "done"
    answer = "".join(event.get("content", "") for event in events)
    assert "provide the building" in answer and "AED" not in answer
    model.assert_not_called()
    assert finish.await_args.args[7]["total_tokens"] == 0


async def test_disabled_membership_cannot_claim_or_execute(turn, monkeypatch):
    db, claim, finish = turn
    monkeypatch.setattr(service, "_authorize_tools", AsyncMock(return_value=False))
    events = decode(
        [event async for event in service.stream_chat_response(db, 3, "hello", "owner", "org")]
    )
    assert events[0]["code"] == "unauthorized"
    claim.assert_not_awaited()
    finish.assert_not_awaited()


def test_large_stored_evidence_does_not_erase_entity_binding_from_history():
    from pydantic_ai.messages import UserPromptPart

    from app.chat.models import Message

    history = service._bounded_history(
        [
            Message(
                id=1,
                conversation_id=1,
                role="user",
                content="Use Fixture Tower",
                meta_data={"turn_status": "complete"},
            ),
            Message(
                id=2,
                conversation_id=1,
                role="assistant",
                content="Here is the evidence",
                meta_data={"evidence": "x" * 190000},
            ),
        ]
    )
    assert any(
        isinstance(part, UserPromptPart) and part.content == "Use Fixture Tower"
        for message in history
        for part in message.parts
    )


async def test_unknown_artifact_tool_cannot_bypass_mcp_and_read_database(turn, monkeypatch):
    from pydantic_ai.messages import RetryPromptPart
    from pydantic_ai.models.function import DeltaToolCall, FunctionModel

    from app.chat import artifacts

    db, _, _ = turn
    fetch = AsyncMock()
    monkeypatch.setattr(artifacts, "_fetch_artifact", fetch)

    async def scripted(messages, info):
        if not any(
            isinstance(part, RetryPromptPart) for message in messages for part in message.parts
        ):
            yield {
                0: DeltaToolCall(
                    name="show_listings", json_args='{"area":"private"}', tool_call_id="bypass"
                )
            }
        else:
            yield "The requested tool is unavailable."

    with service.agent.override(model=FunctionModel(stream_function=scripted)):
        events = decode(
            [
                event
                async for event in service.stream_chat_response(
                    db, 3, "Show listings", "owner", "org"
                )
            ]
        )
    fetch.assert_not_awaited()
    assert not any(event["type"].startswith("artifact_") for event in events)
