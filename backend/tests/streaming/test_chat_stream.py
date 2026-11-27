import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.chat.errors import ERRORS, error_event
from app.crm.assistant import service
from app.crm.assistant.dependencies import ChatDependencies


@pytest.fixture(autouse=True)
def offline_admission(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("lease", 160_000)),
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    # The turn reads the user's CRM role from the database; these turns have none.
    monkeypatch.setattr(service, "role_context", AsyncMock(return_value=""))


async def test_disabled_rollout_never_reserves_quota_or_saves_a_message(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", False)
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    events = [event async for event in service.stream_chat_response(None, 3, "hello", "u", "o")]
    assert decode(events) == [error_event("assistant_disabled")]
    service.admission.acquire.assert_not_awaited()
    save.assert_not_awaited()


def decode(events):
    return [json.loads(event.removeprefix("data: ").strip()) for event in events]


async def test_typed_rollout_preserves_stream_and_accounts_for_routing_usage(monkeypatch):
    from pydantic_ai.models.test import TestModel

    from app.crm.assistant import routing

    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", True)
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    legacy = AsyncMock(side_effect=AssertionError("Rollout must use the typed router"))
    monkeypatch.setattr(service, "agent", SimpleNamespace(run=legacy))
    with (
        routing.router_agent.override(
            model=TestModel(
                custom_output_args={
                    "decision": "route",
                    "workflows": ["crm"],
                    "unavailable_reason": None,
                }
            )
        ),
        routing.crm_agent.override(
            model=TestModel(call_tools=[], custom_output_text="Scope unavailable")
        ),
    ):
        events = [
            event
            async for event in service.stream_chat_response(AsyncMock(), 3, "My leads", "u", "o")
        ]
    assert decode(events) == [
        {"type": "thinking"},
        {"type": "content", "content": "Scope unavailable"},
        {"type": "done"},
    ]
    assert service.admission.finish.await_args.args[1].requests == 2
    assert service.admission.finish.await_args.kwargs["successful"] is True
    assert save.await_args_list[-1].args[3] == "Scope unavailable"
    legacy.assert_not_awaited()


async def test_missing_conversation_emits_only_error(monkeypatch):
    lookup = AsyncMock(return_value=None)
    save = AsyncMock()
    monkeypatch.setattr(service, "get_conversation", lookup)
    monkeypatch.setattr(service, "add_message", save)
    events = [
        event async for event in service.stream_chat_response(None, 3, "hello", "other", "org")
    ]
    assert decode(events) == [error_event("conversation_not_found")]
    save.assert_not_awaited()


async def test_provider_failure_keeps_user_message_and_emits_no_done(monkeypatch, caplog):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    save = AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))

    async def fail(*args, **kwargs):
        assert kwargs["deps"] == ChatDependencies(
            user_id="owner", organization_id="org", conversation_id=3
        )
        raise RuntimeError("private SQL parameters and customer phone must never reach the client")

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=fail))
    db = AsyncMock()
    events = [event async for event in service.stream_chat_response(db, 3, "hello", "owner", "org")]
    [thinking, failed] = decode(events)
    assert thinking == {"type": "thinking"}
    assert failed == {**error_event("internal_error"), "reference": failed["reference"]}
    save.assert_awaited_once_with(db, 3, "user", "hello", user_id="owner", organization_id="org")
    assert service.admission.finish.await_args.kwargs["successful"] is False
    assert "private SQL parameters" not in caplog.text


async def test_text_turn_settles_shared_observed_usage_after_answer(monkeypatch):
    from pydantic_ai.models.test import TestModel

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    actions = []

    async def save(db, conversation_id, role, content, meta_data=None, **scope):
        actions.append((role, content, meta_data))

    async def usage(lease_id, observed, *, successful):
        assert lease_id == "lease" and successful
        actions.append(("usage", observed.total_tokens))

    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service.admission, "finish", usage)
    with service.agent.override(model=TestModel(call_tools=[], custom_output_text="Known answer")):
        events = [
            event
            async for event in service.stream_chat_response(AsyncMock(), 3, "hello", "owner", "org")
        ]
    decoded = decode(events)
    assert decoded[0] == {"type": "thinking"}
    assert (
        "".join(item["content"] for item in decoded if item["type"] == "content") == "Known answer"
    )
    assert decoded[-1] == {"type": "done"}
    assert [action[0] for action in actions] == ["user", "assistant", "usage"]
    assert actions[1][1] == "Known answer"
    assert actions[1][2] == {
        "total_tokens": actions[2][1],
        "guardrail_version": 1,
        "private": False,
    }


async def test_cancellation_settles_partial_observed_usage_without_refunding_reservation(
    monkeypatch,
):
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())
    started = asyncio.Event()

    async def run(*args, usage, **kwargs):
        usage.input_tokens = 123
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))

    async def consume():
        return [
            item
            async for item in service.stream_chat_response(AsyncMock(), 3, "hello", "owner", "org")
        ]

    task = asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    service.admission.finish.assert_awaited_once()
    call = service.admission.finish.await_args
    assert call.args[1].input_tokens == 123 and call.kwargs["successful"] is False


@pytest.mark.parametrize(
    ("refusal", "code"),
    [
        (service.admission.AdmissionRefused("busy"), "turn_in_progress"),
        (service.admission.AdmissionRefused("allowance"), "insufficient_allowance"),
        (HTTPException(403, "Account is unavailable"), "account_unavailable"),
        (TimeoutError(), "service_busy"),
    ],
)
async def test_admission_rejection_never_saves_or_calls_model(monkeypatch, refusal, code):
    """Each refusal says why with its own code; nothing is reserved, saved or run."""
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=True))
    save, run = AsyncMock(), AsyncMock()
    monkeypatch.setattr(service, "add_message", save)
    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    db = AsyncMock()

    async def reject(**kwargs):
        db.commit.assert_awaited_once()  # Release the connection before acquiring another.
        raise refusal

    monkeypatch.setattr(service.admission, "acquire", reject)
    events = [item async for item in service.stream_chat_response(db, 3, "hello", "owner", "org")]
    [event] = decode(events)
    assert event["code"] == code and event["error"] == ERRORS[code][0]
    if code == "insufficient_allowance":
        # Usage is counted per UTC day: it resets at the next UTC midnight.
        assert event["resets_at"].endswith("T00:00:00+00:00")
    assert "Account is unavailable" not in json.dumps(event)  # Raw detail never sent.
    save.assert_not_awaited()
    run.assert_not_awaited()
    service.admission.finish.assert_not_awaited()


async def test_long_turn_streams_tool_progress_before_the_validated_answer(monkeypatch):
    from app.chat.budget import turn_limits

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())
    seen = []

    async def run(*args, deps, usage_limits, **kwargs):
        seen.append((deps.usage_limits, usage_limits))
        deps.progress(
            {"type": "tool_call_start", "tool": "retrieve_personal_crm", "tool_call_id": "a"}
        )
        await asyncio.sleep(0)
        deps.progress(
            {"type": "tool_call_result", "tool": "retrieve_personal_crm", "tool_call_id": "a"}
        )
        return SimpleNamespace(output="Three leads are qualified.")

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    events = [e async for e in service.stream_chat_response(AsyncMock(), 3, "hi", "u", "o")]
    assert [event["type"] for event in decode(events)] == [
        "thinking",
        "tool_call_start",
        "tool_call_result",
        "content",
        "done",
    ]
    # The turn's limits come from its reservation and reach nested workflows via deps.
    assert seen == [(turn_limits(160_000), turn_limits(160_000))]


async def test_exhausted_turn_budget_explains_how_to_continue(monkeypatch):
    from pydantic_ai.exceptions import UsageLimitExceeded

    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())

    async def run(*args, usage, **kwargs):
        usage.input_tokens = 5_000
        raise UsageLimitExceeded("Exceeded the total_tokens_limit")

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    events = decode([e async for e in service.stream_chat_response(AsyncMock(), 3, "hi", "u", "o")])
    assert events[-1]["code"] == "turn_budget_exceeded"
    assert events[-1]["error"].startswith("This question needed more research steps")
    assert service.admission.finish.await_args.args[1].input_tokens == 5_000
