"""Market AI and CRM Operations Assistant have separate capabilities and histories."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from app.chat.models import Message
from app.crm.assistant import service
from app.crm.assistant.agent import _convert_to_pydantic_messages
from app.crm.assistant.agent import agent as crm_coordinator
from app.market_ai import routing as market_routing
from app.market_ai import workflows as market_workflows
from app.market_ai.agent import agent as market_coordinator
from app.market_ai.router import MARKET_AI


@pytest.fixture(autouse=True)
def turn(monkeypatch):
    monkeypatch.setattr(service.settings, "ASSISTANT_ENABLED", True)
    monkeypatch.setattr(service.settings, "ASSISTANT_TYPED_ROUTING_ENABLED", False)
    monkeypatch.setattr(
        service.admission,
        "acquire",
        AsyncMock(return_value=service.admission.TurnLease("lease", 160_000)),
    )
    monkeypatch.setattr(service.admission, "finish", AsyncMock())
    monkeypatch.setattr(service, "get_conversation", AsyncMock(return_value=SimpleNamespace(id=3)))
    monkeypatch.setattr(service, "get_conversation_messages", AsyncMock(return_value=[]))
    # The turn reads the user's CRM role from the database; these turns have none.
    monkeypatch.setattr(service, "role_context", AsyncMock(return_value=""))
    saved = AsyncMock()
    monkeypatch.setattr(service, "add_message", saved)
    return saved


def delegate_to(tool):
    def coordinator(messages, info):
        if any(isinstance(p, ToolReturnPart) for m in messages for p in m.parts):
            return ModelResponse(parts=[TextPart("Answered.")])
        return ModelResponse(parts=[ToolCallPart(tool, {"question": "JVC sales last month"})])

    return FunctionModel(coordinator)


def decode(events):
    return [json.loads(event.removeprefix("data: ")) for event in events]


def test_market_ai_keeps_its_market_and_pricing_workflows():
    assert set(market_coordinator._function_toolset.tools) == {
        "research_market",
        "analyze_pricing",
    }
    assert set(market_routing.Workflow.__args__) == {"market", "pricing"}
    assert "query_market_metrics" in market_workflows.market_agent._function_toolset.tools
    assert "comparable_evidence" in market_workflows.pricing_agent._function_toolset.tools
    assert MARKET_AI.agent is market_coordinator
    assert MARKET_AI.run_routed_turn is market_routing.run_routed_turn


async def test_market_ai_refuses_crm_questions_without_running_a_workflow(monkeypatch):
    market_run = AsyncMock(side_effect=AssertionError("CRM query reached market workflow"))
    pricing_run = AsyncMock(side_effect=AssertionError("CRM query reached pricing workflow"))
    monkeypatch.setattr(market_routing, "market_agent", SimpleNamespace(run=market_run))
    monkeypatch.setattr(market_routing, "pricing_agent", SimpleNamespace(run=pricing_run))
    with market_routing.router_agent.override(
        model=TestModel(
            custom_output_args={
                "decision": "unsupported",
                "workflows": [],
                "unavailable_reason": "crm_operations",
            }
        )
    ):
        result = await market_routing.run_routed_turn(
            "How many leads do we have?", deps=SimpleNamespace(), usage=RunUsage()
        )
    assert "CRM Operations Assistant" in result.output
    assert result.decision.workflows == []
    market_run.assert_not_awaited()
    pricing_run.assert_not_awaited()


def test_the_crm_assistant_has_no_market_workflow_to_select():
    assert not {"research_market", "analyze_pricing"} & set(crm_coordinator._function_toolset.tools)
    from app.crm.assistant import routing as crm_routing

    assert set(crm_routing.Workflow.__args__) == {"crm", "followup", "action"}


async def test_market_ai_chat_runs_its_market_workflow_and_tags_its_answer(turn):
    market_ran = []

    def market_specialist(messages, info):
        market_ran.append(True)
        return ModelResponse(parts=[TextPart("12 sales in JVC.")])

    with (
        market_coordinator.override(model=delegate_to("research_market")),
        market_workflows.market_agent.override(model=FunctionModel(market_specialist)),
    ):
        events = decode(
            [
                e
                async for e in service.stream_chat_response(
                    AsyncMock(), 3, "JVC sales last month", "u", "o", runtime=MARKET_AI
                )
            ]
        )
    assert market_ran == [True]
    assert [e["type"] for e in events] == [
        "thinking",
        "tool_call_start",
        "tool_call_result",
        "content",
        "done",
    ]
    assert events[1]["tool"] == "research_market"
    meta = turn.await_args_list[-1].args[4]
    assert meta["assistant"] == "market"


async def test_the_crm_endpoint_runs_the_crm_coordinator_never_market(turn, monkeypatch):
    def forbidden(messages, info):
        raise AssertionError("The CRM assistant must never run Market AI")

    with (
        crm_coordinator.override(model=TestModel(call_tools=[], custom_output_text="Two leads.")),
        market_coordinator.override(model=FunctionModel(forbidden)),
        market_workflows.market_agent.override(model=FunctionModel(forbidden)),
        market_workflows.pricing_agent.override(model=FunctionModel(forbidden)),
    ):
        events = decode(
            [e async for e in service.stream_chat_response(AsyncMock(), 3, "My leads", "u", "o")]
        )
    assert events[-2:] == [{"type": "content", "content": "Two leads."}, {"type": "done"}]
    assert "assistant" not in turn.await_args_list[-1].args[4]


def test_market_answers_in_a_shared_conversation_never_reach_the_crm_model():
    messages = [
        Message(conversation_id=1, role="user", content="JVC sales?"),
        Message(
            conversation_id=1,
            role="assistant",
            content="Market answer: 12 sales",
            meta_data={"guardrail_version": 1, "assistant": "market"},
        ),
        Message(conversation_id=1, role="user", content="My leads?"),
        Message(
            conversation_id=1,
            role="assistant",
            content="CRM answer: two leads",
            meta_data={"guardrail_version": 1},
        ),
    ]
    crm = str(_convert_to_pydantic_messages(messages))
    market = str(_convert_to_pydantic_messages(messages, include_market=True))
    assert "Market answer" not in crm and "CRM answer" in crm
    assert "Market answer" in market and "CRM answer" not in market


def test_market_ai_keeps_its_market_source_labels():
    from app.chat.security import safe_data
    from app.market_ai.sources import market_sources

    raw = {"sources": {"dld/matched": 3, "dxbi/matched": 4}, "source": "pf_listings"}
    assert safe_data(market_sources(raw)) == {
        "sources": {"DLD registered transactions": 3, "DXBI records": 4},
        "source": "Property Finder asking listings",
    }
    # The CRM keeps a lead's own source as stored.
    assert safe_data({"source": "Property Finder"}) == {"source": "Property Finder"}
