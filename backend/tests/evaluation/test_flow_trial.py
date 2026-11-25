import json

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from scripts.evaluation.flow_trial import WORKFLOWS, leaf_tools, load_flow_cases, run_flow_case


def test_all_application_leaf_tools_are_replaced_and_catalog_covers_both_channels():
    cases = load_flow_cases()
    assert {case["flow"] for case in cases} == {"routed", "customer"}
    assert any(len(case.get("turns", [])) > 1 for case in cases)
    for case in cases:
        for workflow in WORKFLOWS:
            assert {tool.name for tool in leaf_tools(case, [], workflow)} == set(
                workflow._function_toolset.tools
            )


async def test_actual_typed_router_and_crm_specialist_share_synthetic_leaf_evidence(monkeypatch):
    from app.crm.assistant import crm_tools
    from app.market_ai import routing

    async def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation may not execute a production data operation")

    monkeypatch.setattr(crm_tools, "query_my_crm_records", forbidden)
    calls = []

    def respond(messages, info):
        calls.append(info)
        if info.output_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"decision": "route", "workflows": ["crm"], "unavailable_reason": None},
                    )
                ]
            )
        if not any(
            getattr(part, "tool_name", None) == "query_my_crm_records"
            for message in messages
            for part in message.parts
        ):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "query_my_crm_records", {"resource": "leads", "summary_only": True}
                    )
                ]
            )
        return ModelResponse(
            parts=[TextPart("Your own CRM has three leads: two new and one qualified.")]
        )

    case = next(case for case in load_flow_cases() if case["id"] == "route_crm")
    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert record["turns"][0]["decision"]["workflows"] == ["crm"]
    assert record["calls"][0]["tool"] == "query_my_crm_records"
    assert len(calls) == 3  # Real router, specialist tool selection, specialist answer.
    assert routing.router_agent._function_toolset.tools == {}


async def test_actual_customer_policy_qualifies_without_database_or_send(monkeypatch):
    from app.whatsapp import customer_agent

    def respond(messages, info):
        tool = info.output_tools[0]
        if "topic" in tool.parameters_json_schema["properties"]:
            output = {
                "topic": "property",
                "risk": "routine",
                "confidence": 0.99,
                "reason": "An explicit property search needs a transaction preference.",
                "next_question": "transaction",
            }
        else:
            output = {
                "response_kind": "clarify",
                "missing_detail": "transaction",
                "evidence_ids": [],
                "risk": "routine",
                "reply": "Nice area. Are you looking to buy or rent?",
            }
        return ModelResponse(parts=[ToolCallPart(tool.name, output)])

    case = {
        "id": "test_customer",
        "question": "Looking for a two bedroom apartment in Marina.",
        "flow": "customer",
        "category": "whatsapp",
        "tools": {},
    }
    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert record["answer"] == "Nice area. Are you looking to buy or rent?"
    assert record["turns"][0]["draft"]["auto_eligible"] is True
    assert customer_agent.classifier()._function_toolset.tools == {}
    assert customer_agent.drafter()._function_toolset.tools == {}


async def test_customer_personal_content_never_calls_any_provider():
    def forbidden(messages, info):
        raise AssertionError("Personal messages must remain silent")

    case = next(case for case in load_flow_cases() if case["id"] == "wa_personal")
    record = await run_flow_case(case, FunctionModel(forbidden))
    assert record["turns"][0]["draft"] is None
    assert record["answer"] == ""
    assert json.dumps(record)


async def test_changed_budget_multiturn_fixture_is_fresh_for_each_candidate():
    original = next(case for case in load_flow_cases() if case["id"] == "route_multiturn")
    assert (
        original["tools"]["query_my_crm_records"]["records"][0]["criteria"]["budget_max_aed"]
        == 1200000
    )

    def respond(messages, info):
        if info.output_tools:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        info.output_tools[0].name,
                        {"decision": "route", "workflows": ["crm"], "unavailable_reason": None},
                    )
                ]
            )
        returns = [
            part
            for message in messages
            for part in message.parts
            if getattr(part, "tool_name", None) == "query_my_crm_records"
            and hasattr(part, "content")
        ]
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart("query_my_crm_records", {"resource": "leads", "record_id": 101})
                ]
            )
        budget = returns[-1].content["records"][0]["criteria"]["budget_max_aed"]
        return ModelResponse(parts=[TextPart(f"Leena's current budget is AED {budget}.")])

    for _candidate in range(2):
        record = await run_flow_case(original, FunctionModel(respond))
        assert "error_type" not in record
        assert "1200000" in record["turns"][0]["answer"]
        assert "1500000" in record["turns"][1]["answer"]
        assert all(turn["calls"] for turn in record["turns"])
    assert (
        original["tools"]["query_my_crm_records"]["records"][0]["criteria"]["budget_max_aed"]
        == 1200000
    )


async def test_customer_retrieval_callback_uses_only_matching_synthetic_public_evidence():
    case = next(case for case in load_flow_cases() if case["id"] == "wa_listing_retrieval")

    def respond(messages, info):
        tool = info.output_tools[0]
        if "topic" in tool.parameters_json_schema["properties"]:
            output = {
                "topic": "property",
                "risk": "routine",
                "confidence": 0.99,
                "reason": "Complete rental search preferences; use public published listings only.",
                "next_question": None,
                "retrieval": {
                    "operation": "published_listings",
                    "location": "Dubai Marina",
                    "transaction": "rent",
                    "property_type": "apartment",
                    "bedrooms": 2,
                    "max_price_aed": 120000.0,
                },
            }
        else:
            output = {
                "response_kind": "facts",
                "evidence_ids": ["listing:synthetic-101:1"],
                "risk": "routine",
                "missing_detail": None,
            }
        return ModelResponse(parts=[ToolCallPart(tool.name, output)])

    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert "AED 115,000" in record["answer"]
    assert record["calls"][0]["tool"] == "customer_retrieval"
    assert record["calls"][0]["valid"] is True
    assert record["turns"][0]["draft"]["evidence_snapshots"][0]["listing_id"] == "synthetic-101"


async def test_customer_text_cannot_enable_market_retrieval_disabled_by_trusted_context():
    case = next(case for case in load_flow_cases() if case["id"] == "wa_market_disabled")

    def respond(messages, info):
        tool = info.output_tools[0]
        if "topic" in tool.parameters_json_schema["properties"]:
            output = {
                "topic": "property",
                "risk": "routine",
                "confidence": 0.99,
                "reason": "A factual market rental query.",
                "next_question": None,
                "retrieval": {
                    "operation": "market_summary",
                    "dataset": "rentals",
                    "location": "Dubai Marina",
                    "period": "previous_month",
                },
            }
        else:
            payload = json.loads(
                next(
                    part.content
                    for message in reversed(messages)
                    for part in reversed(message.parts)
                    if getattr(part, "part_kind", None) == "user-prompt"
                )
            )
            assert payload["approved_facts"] == []
            output = {
                "response_kind": "handoff",
                "evidence_ids": [],
                "risk": "approval",
                "missing_detail": None,
            }
        return ModelResponse(parts=[ToolCallPart(tool.name, output)])

    record = await run_flow_case(case, FunctionModel(respond))
    assert "error_type" not in record
    assert record["calls"][0]["allowed"] is False
    assert record["turns"][0]["draft"]["auto_eligible"] is False
    assert record["turns"][0]["draft"]["evidence_snapshots"] == []
    assert "100,000" not in record["answer"]
