"""Each way a turn can fail reaches the browser as its own stable code, and every outcome
settles the turn's reservation with the usage the provider actually reported.

The model is a stub: these are the exceptions pydantic-ai raises for provider responses.
Raw exception text (which may hold provider bodies, SQL or customer data) never leaves the
server; an unexpected failure is logged and sent with only a random reference.
"""

import asyncio
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)

from app.chat import errors
from app.crm.assistant import service

SECRET = "sk-or-v1-secret provider body with SELECT phone FROM crm and +971500000009"


@pytest.fixture(autouse=True)
def turn(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("lease", 160_000)),
    )
    settled = []

    async def finish(lease_id, usage, *, successful):
        settled.append((lease_id, usage.total_tokens, successful))

    monkeypatch.setattr(service.admission, "finish", finish)
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr(service, "add_message", AsyncMock())
    return settled


def failing(exc, observed=0):
    async def run(*args, usage, **kwargs):
        usage.input_tokens += observed  # What the provider reported before failing.
        raise exc

    return SimpleNamespace(run=run)


async def events(message="hello"):
    return [
        json.loads(item.removeprefix("data: "))
        async for item in service.stream_chat_response(AsyncMock(), 3, message, "u", "o")
    ]


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (UsageLimitExceeded("Exceeded the total_tokens_limit of 160000"), "turn_budget_exceeded"),
        (ModelHTTPError(429, "model", body=SECRET), "provider_rate_limited"),
        (ModelHTTPError(503, "model", body=SECRET), "provider_unavailable"),
        (ModelHTTPError(504, "model", body=SECRET), "provider_timeout"),
        (ModelAPIError("model", SECRET), "provider_unavailable"),
        (TimeoutError(), "provider_timeout"),
        (UnexpectedModelBehavior(SECRET), "provider_invalid_response"),
        (ModelHTTPError(400, "model", body=SECRET), "internal_error"),
        (RuntimeError(SECRET), "internal_error"),
        (
            ExceptionGroup("tools", [ModelHTTPError(429, "model", body=SECRET)]),
            "provider_rate_limited",
        ),
    ],
)
async def test_each_failure_has_its_code_and_settles_observed_usage(
    monkeypatch, turn, caplog, exc, code
):
    monkeypatch.setattr(service, "agent", failing(exc, observed=1_234))
    caplog.set_level(logging.ERROR)
    sent = await events()
    assert [event["type"] for event in sent] == ["thinking", "error"]
    failed = sent[-1]
    message, retryable = errors.ERRORS[code]
    assert failed == {
        "type": "error",
        "code": code,
        "error": message,
        "retryable": retryable,
        "reference": failed["reference"],
    }
    # The browser gets a reference to quote; the log has it with the code and exception type.
    assert len(failed["reference"]) == 12
    assert f"code={code} reference={failed['reference']}" in caplog.text
    assert type(exc).__name__ in caplog.text
    # Nothing raw reaches the browser or the log.
    for leaked in ("sk-or-v1", "SELECT", "+971500000009", "provider body"):
        assert leaked not in json.dumps(sent) and leaked not in caplog.text
    # Failed, charged exactly what the provider reported; the reservation is released.
    assert turn == [("lease", 1_234, False)]


def test_the_budget_message_is_not_the_generic_one():
    assert errors.ERRORS["turn_budget_exceeded"][0] != errors.ERRORS["internal_error"][0]
    assert "narrow" in errors.ERRORS["provider_timeout"][0]
    assert "one area, project or record" in errors.ERRORS["turn_budget_exceeded"][0]


def test_an_unknown_code_falls_back_to_the_generic_safe_error():
    assert errors.error_event("made_up") == errors.error_event("internal_error")


async def test_a_successful_turn_settles_as_successful(monkeypatch, turn):
    async def run(*args, usage, **kwargs):
        usage.input_tokens += 900
        return SimpleNamespace(output="Stored answer.")

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    sent = await events()
    assert [event["type"] for event in sent] == ["thinking", "content", "done"]
    assert turn == [("lease", 900, True)]


async def test_an_empty_answer_is_an_answer_not_an_error(monkeypatch, turn):
    monkeypatch.setattr(
        service, "agent", SimpleNamespace(run=AsyncMock(return_value=SimpleNamespace(output="")))
    )
    sent = await events()
    assert [event["type"] for event in sent] == ["thinking", "content", "done"]
    assert sent[1]["content"] == ""


async def test_a_closed_browser_stream_cancels_the_turn_and_charges_only_observed(
    monkeypatch, turn
):
    """The user navigates away mid-turn: the provider call is cancelled, the turn settles as
    failed with what was already reported, and nothing is charged for the unfinished request."""
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def run(*args, usage, **kwargs):
        usage.input_tokens += 700  # One request completed and reported.
        started.set()
        try:
            await asyncio.sleep(3600)  # The next request never returns.
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(service, "agent", SimpleNamespace(run=run))
    stream = service.stream_chat_response(AsyncMock(), 3, "hello", "u", "o")
    assert json.loads((await anext(stream)).removeprefix("data: ")) == {"type": "thinking"}
    pending = asyncio.ensure_future(anext(stream))
    await started.wait()
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    await stream.aclose()
    assert cancelled.is_set()
    assert turn == [("lease", 700, False)]


async def test_an_exhausted_daily_allowance_is_refused_before_streaming_with_its_figures(
    monkeypatch,
):
    """The 429 before any stream carries a code, the user's own figures and the reset time,
    in the API's structured {code, message} form, so the browser need not parse text."""
    from fastapi import HTTPException

    from app.core import dependencies

    monkeypatch.setattr(
        dependencies.token_usage_service,
        "get_today_usage",
        AsyncMock(return_value=SimpleNamespace(total_tokens=1_000_000)),
    )
    monkeypatch.setattr(
        dependencies,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(daily_token_limit=1_000_000)),
    )
    with pytest.raises(HTTPException) as refused:
        await dependencies.require_token_quota(
            request=None, db=None, current_user=SimpleNamespace(id="u")
        )
    assert refused.value.status_code == 429
    detail = refused.value.detail
    assert detail["code"] == "daily_limit_reached" and detail["retryable"] is False
    assert (detail["tokens_used"], detail["daily_limit"]) == (1_000_000, 1_000_000)
    assert detail["resets_at"].endswith("T00:00:00+00:00")
    assert detail["message"] == errors.ERRORS["daily_limit_reached"][0]


async def test_a_turn_under_the_daily_allowance_is_not_refused(monkeypatch):
    from app.core import dependencies

    monkeypatch.setattr(
        dependencies.token_usage_service,
        "get_today_usage",
        AsyncMock(return_value=SimpleNamespace(total_tokens=221_653)),
    )
    monkeypatch.setattr(
        dependencies,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(daily_token_limit=1_000_000)),
    )
    assert (
        await dependencies.require_token_quota(
            request=None, db=None, current_user=SimpleNamespace(id="u")
        )
        is None
    )
