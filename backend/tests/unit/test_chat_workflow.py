from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from app.crm.assistant import workflows
from app.crm.assistant.agent import agent
from app.crm.assistant.dependencies import ChatDependencies
from app.crm.assistant.workflows import LIMITS, action_agent, crm_agent, followup_agent


async def test_orchestrator_delegates_with_shared_identity_to_crm_workflows_only():
    def orchestrator(messages, info):
        if not any(
            isinstance(part, ToolReturnPart) for message in messages for part in message.parts
        ):
            return ModelResponse(
                parts=[ToolCallPart("retrieve_personal_crm", {"question": "My leads"})]
            )
        return ModelResponse(parts=[TextPart("You have no matching leads.")])

    deps = ChatDependencies("user", "org", conversation_id=1)
    with (
        agent.override(model=FunctionModel(orchestrator)),
        crm_agent.override(
            model=TestModel(call_tools=[], custom_output_text="You have no matching leads.")
        ),
    ):
        result = await agent.run("My leads", deps=deps, usage_limits=LIMITS)
    assert result.usage().requests == 3
    assert "no matching leads" in result.output
    # CRM Operations only: no market research or pricing workflow is registered.
    assert set(agent._function_toolset.tools) == {
        "retrieve_personal_crm",
        "plan_followups",
        "prepare_action",
    }


def test_specialists_have_narrow_tools_and_no_execution_capability():
    # Calendar and lead-email tools only read stored rows; proposing stays the one write path.
    assert set(crm_agent._function_toolset.tools) == {
        "query_my_crm_records",
        "query_my_calendar",
        "query_my_lead_emails",
        # Read-only: rechecks access and notes the request in turn evidence; writes nothing.
        "hold_pending_request",
    }
    assert set(action_agent._function_toolset.tools) == {
        "query_my_crm_records",
        "query_my_calendar",
        "propose_crm_action",
        "find_assignment_colleagues",
        "find_meeting_colleagues",
        # Team management lookups (organization owners and administrators only).
        "find_teams",
        "find_team_people",
        "hold_pending_request",
    }
    assert "propose_crm_action" not in followup_agent._function_toolset.tools
    # No market specialist exists in the CRM assistant.
    assert not hasattr(workflows, "market_agent") and not hasattr(workflows, "pricing_agent")
    assert (
        LIMITS.request_limit == 20
        and LIMITS.tool_calls_limit == 24
        and LIMITS.total_tokens_limit == 160_000
    )


async def test_recursive_workflow_requests_share_and_exhaust_one_turn_budget():
    import pytest
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.usage import RunUsage, UsageLimits

    def repeat(messages, info):
        return ModelResponse(parts=[ToolCallPart("retrieve_personal_crm", {"question": "Repeat"})])

    usage = RunUsage()
    with (
        agent.override(model=FunctionModel(repeat)),
        crm_agent.override(model=TestModel(call_tools=[], custom_output_text="No stored records")),
    ):
        with pytest.raises(UsageLimitExceeded):
            await agent.run(
                "Repeat",
                deps=ChatDependencies("u", "o"),
                usage=usage,
                usage_limits=UsageLimits(request_limit=4),
            )
    assert usage.requests <= 4


def test_private_followup_replays_only_reauthorized_lookup_handles():
    from app.chat.models import Message
    from app.crm.assistant.agent import _convert_to_pydantic_messages

    message = Message(
        conversation_id=1,
        role="assistant",
        content="Private customer salary",
        meta_data={
            "private": True,
            "guardrail_version": 1,
            "_retrieval_context": [{"resource": "leads", "record_id": 3}],
        },
    )
    history = _convert_to_pydantic_messages([message])
    assert len(history) == 1
    assert '"record_id": 3' in history[0].parts[0].content
    assert "Private customer salary" not in history[0].parts[0].content
    assert "Retrieve the records afresh" in history[0].parts[0].content
