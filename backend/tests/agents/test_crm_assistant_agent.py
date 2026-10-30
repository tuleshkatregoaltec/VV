"""The assistant's tools cannot be steered to another organisation, and its prompt keeps it to
the CRM and treats lead text as data."""

import inspect
from itertools import chain
from types import SimpleNamespace

from pydantic_ai.messages import ModelResponse, SystemPromptPart, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.crm.assistant.agent import assistant_agent
from app.crm.assistant.deps import AssistantDeps
from app.crm.assistant.tools import SECTION_TOOLS

SCOPE_NAMES = {"organization_id", "org_id", "user_id", "organization", "user"}


def _deps():
    return AssistantDeps(
        db=None,
        user_id="user-1",
        organization_id="org-a",
        organization_name="Acme Realty",
        role="member",
        organization=SimpleNamespace(id="org-a", name="Acme Realty"),
    )


def test_no_tool_exposes_scope_parameters():
    for tool in chain(*SECTION_TOOLS.values()):
        parameters = set(inspect.signature(tool).parameters) - {"ctx"}
        assert not parameters & SCOPE_NAMES, tool.__name__

    for name, tool in assistant_agent._function_toolset.tools.items():
        properties = tool.tool_def.parameters_json_schema.get("properties", {})
        assert not set(properties) & SCOPE_NAMES, name


def test_every_section_tool_is_registered():
    registered = set(assistant_agent._function_toolset.tools)
    assert registered == {tool.__name__ for tool in chain(*SECTION_TOOLS.values())}


async def test_off_topic_question_gets_refusal_and_no_tool_calls():
    seen_prompts: list[str] = []

    def model(messages, info: AgentInfo) -> ModelResponse:
        seen_prompts.extend(
            part.content
            for message in messages
            for part in message.parts
            if isinstance(part, SystemPromptPart)
        )
        return ModelResponse(
            parts=[TextPart("I can only help with your CRM leads. Try the Market tab.")]
        )

    result = await assistant_agent.run(
        "What's the average price per sqft in JVC?", deps=_deps(), model=FunctionModel(model)
    )

    calls = [
        part
        for message in result.all_messages()
        for part in getattr(message, "parts", [])
        if isinstance(part, ToolCallPart)
    ]
    assert calls == []
    prompt = "\n".join(seen_prompts)
    # The refusal relies on these rules being in the prompt the model sees.
    assert "Acme Realty" in prompt
    assert "Market tab" in prompt
    assert "<lead_data>" in prompt
    assert "propose_" in prompt
