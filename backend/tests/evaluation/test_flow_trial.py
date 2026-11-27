from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from scripts.evaluations.market_ai.flow_trial import (
    WORKFLOWS,
    leaf_tools,
    load_flow_cases,
    run_flow_case,
)


def test_market_flow_catalog_contains_only_market_ai_cases_and_replaces_every_tool():
    cases = load_flow_cases()
    assert {case["flow"] for case in cases} == {"routed"}
    assert {case.get("assistant") for case in cases} == {"market"}
    assert any(len(case.get("turns", [])) > 1 for case in cases)
    for case in cases:
        for workflow in WORKFLOWS:
            assert {tool.name for tool in leaf_tools(case, [], workflow)} == set(
                workflow._function_toolset.tools
            )


async def test_market_routing_uses_only_synthetic_market_tools():
    from app.market_ai import routing

    calls = []

    def respond(messages, info):
        calls.append(info)
        if info.output_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"decision": "route", "workflows": ["market"], "unavailable_reason": None},
                    )
                ]
            )
        if not any(
            getattr(part, "tool_name", None) == "query_market_metrics"
            for message in messages
            for part in message.parts
        ):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_market_metrics",
                        {"dataset": "sales", "location": "JVC", "group_by": "price_band"},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("JVC sales are grounded in the synthetic fixture.")])

    case = next(case for case in load_flow_cases() if case["id"] == "route_market")
    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert record["turns"][0]["decision"]["workflows"] == ["market"]
    assert record["calls"][0]["tool"] == "query_market_metrics"
    assert len(calls) == 3
    assert routing.router_agent._function_toolset.tools == {}


async def test_market_multiturn_fixture_mutation_is_fresh_for_each_candidate():
    case = next(case for case in load_flow_cases() if case["id"] == "route_market_multiturn")

    def respond(messages, info):
        if info.output_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"decision": "route", "workflows": ["market"], "unavailable_reason": None},
                    )
                ]
            )
        if not any(
            getattr(part, "tool_name", None) == "query_market_metrics"
            for message in messages
            for part in message.parts
        ):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_market_metrics",
                        {"dataset": "sales", "location": "JVC", "group_by": "price_band"},
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("JVC sales count and price bands from evidence.")])

    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert len(record["turns"]) == 2
    assert all(turn["decision"]["workflows"] == ["market"] for turn in record["turns"])
