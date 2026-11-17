from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage, UsageLimits

from app.chat import routing
from app.chat.agent import _convert_to_pydantic_messages
from app.chat.dependencies import ChatDependencies
from app.chat.models import Message


def route_model(workflows=None, *, decision="route", reason=None):
    return TestModel(
        custom_output_args={
            "decision": decision,
            "workflows": workflows or [],
            "unavailable_reason": reason,
        }
    )


@pytest.mark.parametrize(
    "values",
    [
        {"decision": "route", "workflows": []},
        {"decision": "route", "workflows": ["crm", "crm"]},
        {"decision": "route", "workflows": ["market", "crm", "action"]},
        {"decision": "route", "workflows": ["execute"]},
        {"decision": "clarify", "workflows": ["action"]},
        {"decision": "unsupported", "workflows": []},
    ],
)
def test_router_schema_cannot_expand_or_repeat_capabilities(values):
    with pytest.raises(ValidationError):
        routing.IntentDecision.model_validate(values)


async def test_single_intent_bypasses_coordinator_and_uses_current_private_context(monkeypatch):
    deps = ChatDependencies("user", "org")
    usage = RunUsage()
    history = _convert_to_pydantic_messages(
        [
            Message(
                conversation_id=1,
                role="assistant",
                content="Stale private salary",
                meta_data={
                    "private": True,
                    "_retrieval_context": [{"resource": "leads", "record_id": 3}],
                },
            )
        ]
    )
    observed = []
    specialist = Agent(TestModel(call_tools=["read_current"]), deps_type=ChatDependencies)

    @specialist.tool
    async def read_current(ctx: RunContext[ChatDependencies]) -> str:
        assert ctx.deps is deps and ctx.usage is usage
        observed.extend(ctx.messages)
        ctx.deps.retrieval_budget["crm_detail_rows"] -= 1
        ctx.deps.evidence.append({"private": True})
        return "Fresh authorized evidence"

    monkeypatch.setattr(routing, "crm_agent", specialist)
    coordinator = AsyncMock(side_effect=AssertionError("Single intent must skip synthesis"))
    monkeypatch.setattr(routing, "coordinator_agent", SimpleNamespace(run=coordinator))
    with routing.router_agent.override(model=route_model(["crm"])):
        result = await routing.run_routed_turn(
            "What is the latest on that lead?", deps=deps, usage=usage, message_history=history
        )
    assert "Fresh authorized evidence" in result.output
    assert usage.requests == 3  # Router plus tool request and grounded specialist response.
    assert deps.evidence and deps.retrieval_budget["crm_detail_rows"] == 9
    assert "Stale private salary" not in str(observed)
    assert "Retrieve the records afresh" in str(observed)
    coordinator.assert_not_awaited()


async def test_mixed_intent_runs_two_specialists_and_one_toolless_synthesis():
    usage = RunUsage()
    with (
        routing.router_agent.override(model=route_model(["market", "crm"])),
        routing.market_agent.override(
            model=TestModel(call_tools=[], custom_output_text="Market missing")
        ),
        routing.crm_agent.override(
            model=TestModel(call_tools=[], custom_output_text="CRM missing")
        ),
        routing.coordinator_agent.override(
            model=TestModel(custom_output_text="Market and CRM unavailable")
        ),
    ):
        result = await routing.run_routed_turn(
            "Compare the market and my leads", deps=ChatDependencies("u", "o"), usage=usage
        )
    assert result.output == "Market and CRM unavailable"
    assert usage.requests == 4
    assert not routing.router_agent._function_toolset.tools
    assert not routing.coordinator_agent._function_toolset.tools


async def test_mixed_turn_budget_includes_router_and_prevents_second_specialist(monkeypatch):
    usage = RunUsage()
    second = AsyncMock(side_effect=AssertionError("Budget must stop the provider request"))
    # Keep a real agent so Pydantic AI checks the shared budget before the model request.
    second_model = TestModel(call_tools=[], custom_output_text="Should never run")
    monkeypatch.setattr(second_model, "request", second)
    with (
        routing.router_agent.override(model=route_model(["market", "crm"])),
        routing.market_agent.override(model=TestModel(call_tools=[], custom_output_text="Missing")),
        routing.crm_agent.override(model=second_model),
    ):
        with pytest.raises(UsageLimitExceeded):
            await routing.run_routed_turn(
                "Compare market and leads",
                deps=ChatDependencies("u", "o"),
                usage=usage,
                usage_limits=UsageLimits(request_limit=2),
            )
    assert usage.requests == 2
    second.assert_not_awaited()


@pytest.mark.parametrize(
    ("decision", "reason", "expected"),
    [
        ("clarify", None, "narrow"),
        ("unsupported", "closed_deal_revenue", "no closed-deal revenue ledger"),
    ],
)
async def test_missing_scope_and_revenue_stop_without_retrieval(
    monkeypatch, decision, reason, expected
):
    specialist = AsyncMock(side_effect=AssertionError("No evidence workflow is appropriate"))
    monkeypatch.setattr(routing, "crm_agent", SimpleNamespace(run=specialist))
    usage = RunUsage()
    with routing.router_agent.override(model=route_model(decision=decision, reason=reason)):
        result = await routing.run_routed_turn(
            "My revenue", deps=ChatDependencies("u", "o"), usage=usage
        )
    assert expected in result.output
    assert usage.requests == 1
    specialist.assert_not_awaited()


async def test_disallowed_input_is_blocked_before_routing():
    usage = RunUsage()
    result = await routing.run_routed_turn(
        "Export all my contacts to CSV", deps=ChatDependencies("u", "o"), usage=usage
    )
    assert result.output == routing.REFUSAL
    assert usage.requests == 0
