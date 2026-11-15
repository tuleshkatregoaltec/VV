"""Turn budgets are sized for real tool-using answers and charged by observed usage.

Live evidence (2026-11-13 14:39): one stream turn made 8 OpenRouter requests totalling
27,374 prompt + 2,142 completion tokens, then failed with UsageLimitExceeded against the
old cumulative 24,000-token turn limit. The user saw "Unable to complete this answer"
and was charged the full 24,000-token reservation.
"""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic_ai import RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage, RunUsage, UsageLimits

from app.chat import admission, budget
from app.chat.agent import _convert_to_pydantic_messages, agent
from app.chat.dependencies import ChatDependencies
from app.chat.models import Message
from app.chat.security import safe_tool
from app.chat.workflows import LIMITS, market_agent

LOGGED_PROMPT_TOKENS = 27_374
LOGGED_COMPLETION_TOKENS = 2_142
LOGGED_REQUESTS = 8
OLD_LIMITS = UsageLimits(request_limit=16, tool_calls_limit=24, total_tokens_limit=24000)


def _logged_usage() -> RequestUsage:
    return RequestUsage(
        input_tokens=LOGGED_PROMPT_TOKENS // LOGGED_REQUESTS,
        output_tokens=LOGGED_COMPLETION_TOKENS // LOGGED_REQUESTS,
    )


@safe_tool
async def stored_metrics(ctx: RunContext[ChatDependencies | None], step: int) -> dict:
    """Return one bounded stored-evidence page."""
    return {"step": step, "rows": [{"area": "Dubai Marina", "median_aed_sqft": 2100}]}


async def _run_logged_turn(limits: UsageLimits, deps: ChatDependencies) -> tuple[str, RunUsage]:
    """Coordinator -> market specialist (5 tool rounds + answer) -> coordinator answer."""

    def coordinator(messages, info):
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(
                parts=[TextPart("Marina medians are stored.")], usage=_logged_usage()
            )
        return ModelResponse(
            parts=[ToolCallPart("research_market", {"question": "Marina prices"})],
            usage=_logged_usage(),
        )

    def specialist(messages, info):
        returns = sum(isinstance(p, ToolReturnPart) for m in messages for p in m.parts)
        if returns < 5:
            return ModelResponse(
                parts=[ToolCallPart("stored_metrics", {"step": returns})], usage=_logged_usage()
            )
        return ModelResponse(parts=[TextPart("Median AED 2,100 per sq ft.")], usage=_logged_usage())

    usage = RunUsage()
    with (
        agent.override(model=FunctionModel(coordinator)),
        market_agent.override(model=FunctionModel(specialist), tools=[stored_metrics]),
    ):
        result = await agent.run("Marina prices", deps=deps, usage=usage, usage_limits=limits)
    return result.output, usage


async def test_logged_eight_request_turn_exceeded_the_old_cumulative_limit():
    deps = ChatDependencies("u", "o", conversation_id=1, usage_limits=OLD_LIMITS)
    with pytest.raises(UsageLimitExceeded):
        await _run_logged_turn(OLD_LIMITS, deps)


async def test_logged_eight_request_turn_completes_within_the_turn_limits():
    deps = ChatDependencies("u", "o", conversation_id=1, usage_limits=LIMITS)
    output, usage = await _run_logged_turn(LIMITS, deps)
    assert output == "Marina medians are stored."
    assert usage.requests == LOGGED_REQUESTS
    # Leaves headroom for a two-workflow turn of the same shape (about 2x).
    assert usage.total_tokens * 2 < LIMITS.total_tokens_limit


async def test_tool_progress_reaches_the_turn_without_model_text_or_arguments():
    events = []
    deps = ChatDependencies(
        "u", "o", conversation_id=1, usage_limits=LIMITS, progress=events.append
    )
    await _run_logged_turn(LIMITS, deps)
    kinds = [(event["type"], event["tool"]) for event in events]
    assert kinds[0] == ("tool_call_start", "research_market")
    assert kinds[-1] == ("tool_call_result", "research_market")
    assert kinds.count(("tool_call_start", "stored_metrics")) == 5
    assert all(set(event) <= {"type", "tool", "tool_call_id"} for event in events)


def test_turn_limits_follow_the_reserved_budget_not_a_fixed_constant():
    limits = budget.turn_limits(50_000)
    assert limits.total_tokens_limit == 50_000
    assert limits.request_limit == LIMITS.request_limit
    assert LIMITS.total_tokens_limit == budget.settings.ASSISTANT_TURN_TOKEN_LIMIT


# --- History is bounded by tokens, not message count ---------------------------------


def _text(role, content):
    return Message(
        conversation_id=1, role=role, content=content, meta_data={"guardrail_version": 1}
    )


def test_history_keeps_newest_messages_within_the_token_budget(monkeypatch):
    monkeypatch.setattr(budget.settings, "ASSISTANT_HISTORY_TOKEN_LIMIT", 2_000)
    messages = []
    for index in range(30):
        messages.append(_text("user", f"question {index} " + "x" * 2_000))
        messages.append(_text("assistant", f"answer {index} " + "y" * 2_000))
    history = _convert_to_pydantic_messages(messages)
    total = sum(budget.estimate_tokens(part.content) for m in history for part in m.parts)
    assert 0 < total <= 2_000
    assert history[-1].parts[0].content.startswith("answer 29")
    assert not any("question 0 " in part.content for m in history for part in m.parts)


def test_private_crm_turns_are_never_replayed_as_history():
    crm = Message(
        conversation_id=1,
        role="assistant",
        content="Lead Sara, +971500000000",
        meta_data={"guardrail_version": 1, "private": True},
    )
    history = _convert_to_pydantic_messages([_text("user", "my leads"), crm])
    assert "+971500000000" not in str(history)


def test_old_tool_outputs_are_compacted_when_a_request_exceeds_the_context_budget(monkeypatch):
    monkeypatch.setattr(budget.settings, "ASSISTANT_REQUEST_CONTEXT_TOKEN_LIMIT", 3_000)
    big = "z" * 6_000  # about 2,000 estimated tokens each
    messages = [ModelRequest(parts=[UserPromptPart("Compare Marina and JVC")])]
    for index in range(3):
        messages.append(
            ModelResponse(parts=[ToolCallPart("stored_metrics", {"step": index}, f"c{index}")])
        )
        messages.append(
            ModelRequest(parts=[ToolReturnPart("stored_metrics", f"{index}:{big}", f"c{index}")])
        )
    compacted = budget.compact_tool_outputs(messages)
    returns = [p for m in compacted for p in m.parts if isinstance(p, ToolReturnPart)]
    assert [p.tool_call_id for p in returns] == ["c0", "c1", "c2"]  # pairs stay intact
    assert returns[-1].content.startswith("2:")  # newest evidence is never trimmed
    assert returns[0].content == budget.COMPACTED_TOOL_OUTPUT
    assert returns[1].content == budget.COMPACTED_TOOL_OUTPUT
    assert budget.estimate_messages(compacted) <= 3_000
    # Originals are not mutated: pydantic-ai keeps the full record for the run.
    assert messages[2].parts[0].content.startswith("0:")


def test_small_contexts_are_left_untouched():
    messages = [
        ModelRequest(parts=[UserPromptPart("Hi")]),
        ModelResponse(parts=[ToolCallPart("stored_metrics", {"step": 0}, "c0")]),
        ModelRequest(parts=[ToolReturnPart("stored_metrics", {"rows": []}, "c0")]),
    ]
    assert budget.compact_tool_outputs(messages) == messages


# --- Admission: per-turn cap, daily allowance, and charging observed usage ----------


class FakeLedger:
    def __init__(self, used=0):
        self.total = used
        self.increments = []
        self.added = []

    async def increment(self, db, user_id, day, prompt, completion, total):
        self.total += total
        self.increments.append((prompt, completion, total))
        return SimpleNamespace(total_tokens=self.total)


@pytest.fixture
def ledger(monkeypatch):
    fake = FakeLedger()

    async def nothing(*args, **kwargs):
        return 0

    monkeypatch.setattr(admission.usage_repository, "increment", fake.increment)
    monkeypatch.setattr(admission.repository, "lock_turn_admission", nothing)
    monkeypatch.setattr(admission.repository, "active_turn_count", nothing)
    return fake


class FakeDb:
    def __init__(self):
        self.added = []

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        pass


async def _reserve(daily_limit, **kwargs):
    db = FakeDb()
    lease = await admission.reserve(
        db, user_id="u", organization_id="o", conversation_id=1, daily_limit=daily_limit, **kwargs
    )
    return lease, db.added[0]


async def test_reservation_is_the_turn_cap_when_the_allowance_allows(ledger):
    lease, row = await _reserve(500_000)
    assert lease.token_budget == admission.settings.ASSISTANT_TURN_TOKEN_LIMIT
    assert row.reserved_tokens == lease.token_budget and ledger.total == lease.token_budget


async def test_reservation_shrinks_to_the_remaining_daily_allowance(ledger):
    ledger.total = 480_000
    lease, _ = await _reserve(500_000)
    assert lease.token_budget == 20_000


async def test_too_little_allowance_refuses_before_reserving(ledger):
    ledger.total = 500_000 - admission.settings.ASSISTANT_TURN_MIN_TOKENS + 1
    with pytest.raises(admission.AdmissionRefused) as refused:
        await _reserve(500_000)
    assert refused.value.code == "allowance"
    assert ledger.total == 500_000 - admission.settings.ASSISTANT_TURN_MIN_TOKENS + 1


def _lease(reserved, *, expired=False):
    now = datetime.now(timezone.utc)
    return admission.ChatTurnLease(
        id="l",
        user_id="u",
        organization_id="o",
        conversation_id=1,
        budget_day=date.today(),
        reserved_tokens=reserved,
        expires_at=now - timedelta(seconds=1) if expired else now + timedelta(seconds=600),
    )


@pytest.mark.parametrize("successful,expired", [(False, False), (True, True), (False, True)])
async def test_failed_or_aborted_turn_is_charged_only_observed_tokens(
    ledger, monkeypatch, successful, expired
):
    lease = _lease(160_000, expired=expired)
    ledger.total = 160_000  # the reservation already charged at admission

    async def locked(db, lease_id):
        return lease

    monkeypatch.setattr(admission.repository, "locked_turn_lease", locked)
    used = RunUsage(input_tokens=LOGGED_PROMPT_TOKENS, output_tokens=LOGGED_COMPLETION_TOKENS)
    await admission.settle(FakeDb(), "l", used, successful=successful)
    assert ledger.total == LOGGED_PROMPT_TOKENS + LOGGED_COMPLETION_TOKENS
    assert lease.status == ("settled" if successful else "failed")


async def test_follow_up_turns_still_send_the_assistant_policy():
    """pydantic-ai adds system_prompt parts only when there is no history; the replayed
    history carries none, so follow-ups previously ran without the policy at all."""
    seen = []

    def model(messages, info):
        seen.append("Never invent figures" in (info.instructions or ""))
        return ModelResponse(parts=[TextPart("ok")])

    history = _convert_to_pydantic_messages([_text("user", "hi"), _text("assistant", "hello")])
    with agent.override(model=FunctionModel(model)):
        await agent.run("first", deps=ChatDependencies("u", "o"))
        await agent.run("follow-up", deps=ChatDependencies("u", "o"), message_history=history)
    assert seen == [True, True]
