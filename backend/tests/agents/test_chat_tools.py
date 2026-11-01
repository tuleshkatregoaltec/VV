from app.chat.agent import agent


def test_registered_chat_tools_preserve_existing_capabilities():
    assert set(agent._function_toolset.tools) == {
        "research_market",
        "analyze_pricing",
        "retrieve_personal_crm",
        "plan_followups",
        "prepare_action",
    }


def test_chat_tool_argument_and_description_contract():
    import json
    from pathlib import Path

    expected = json.loads((Path(__file__).parent / "fixtures/chat_tools.json").read_text())
    actual = {
        name: {"description": tool.description, "schema": tool.function_schema.json_schema}
        for name, tool in agent._function_toolset.tools.items()
    }
    assert actual == expected
