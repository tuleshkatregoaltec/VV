from scripts.evaluation.inventory import build_inventory


def test_mcp_registration_has_bounded_public_capabilities_and_no_static_graph_claim():
    from app.chat import mcp

    definitions = mcp.tool_definitions()
    assert {tool.name for tool in definitions} == {
        "bind_market_scope",
        "query_market_metrics",
        "get_listing_inventory",
        "get_project_delivery_summary",
        "compare_listing_age",
        "compare_listing_rents",
        "compose_market_report",
        "list_broker_enquiries",
        "get_broker_enquiry",
        "match_client_properties",
        "match_property_clients",
        "broker_follow_up_summary",
        "prepare_broker_action",
        "create_broker_document",
        "get_broker_document",
    }
    assert "confirm_broker_action" not in {tool.name for tool in definitions}
    assert {tool.name for tool in definitions if not tool.annotations.readOnlyHint} == {
        "prepare_broker_action",
        "create_broker_document",
    }
    for tool in definitions:
        assert tool.inputSchema["additionalProperties"] is False
        assert tool.inputSchema["required"] == ["request"]
        properties = tool.inputSchema["properties"]["request"]["properties"]
        assert not {"user_id", "organization_id", "reference_date", "sql"} & properties.keys()
    inventory = build_inventory()
    # MCP is dynamically scoped per turn; a static map must retain uncertainty.
    assert "app.chat.mcp.market_mcp" in inventory["functions"]
    assert "app.analytics.market_metrics.get_market_metrics" in inventory["functions"]
    assert "app.listings.capabilities.compare_listing_rents" in inventory["functions"]


def test_declared_legacy_hbu_tools_are_not_assigned_to_selected_production_agents():
    agents = {agent["id"]: agent for agent in build_inventory()["agents"]}
    assert len(agents["app.feasibility.hbu_agent.hbu_seed_agent"]["tools"]) == 7
    assert agents["app.feasibility.hbu_agent.hbu_seed_agent_bts_prefetched"]["tools"] == []
    assert agents["app.feasibility.hbu_agent.hbu_seed_agent_btr"]["tools"] == []
    assert len(agents["app.feasibility.chat_agent.workspace_chat_agent"]["tools"]) == 12


def test_inventory_follows_source_changes_without_importing_application(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    source = app / "agent.py"
    source.write_text("""
from pydantic_ai import Agent
raise RuntimeError("Discovery must not import this module")
PROMPT = "Original prompt"
agent = Agent("provider:model", system_prompt=PROMPT)
async def capability():
    return 1
@agent.tool_plain
async def tool():
    return await capability()
""")
    before = build_inventory(app)
    assert before["agents"][0]["possible_reachable_functions"] == [
        "app.agent.capability",
        "app.agent.tool",
    ]
    source.write_text(
        source.read_text()
        .replace("Original prompt", "Changed prompt")
        .replace("@agent.tool_plain", "# registration removed")
    )
    after = build_inventory(app)
    assert after["agents"][0]["tools"] == []
    assert before["agents"][0]["prompt_sha256"] != after["agents"][0]["prompt_sha256"]


def test_dynamic_dispatch_is_visible_as_uncertainty_not_a_fabricated_edge(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "dynamic.py").write_text("""
async def invoke(choose):
    agent = choose()
    return await agent.run("question")
""")
    inventory = build_inventory(app)
    assert "agent.run" in inventory["functions"]["app.dynamic.invoke"]["unresolved_calls"]
    assert inventory["invocation_candidates"][0]["resolved_callable"] is None


def test_direct_crm_model_calls_are_visible_outside_agent_instrumentation():
    functions = build_inventory()["functions"]
    for name in ("_llm_mapping", "_ai_extract", "_ai_header_mapping"):
        capability = functions[f"app.crm.ai.{name}"]
        assert capability["model_configuration_references"] == ["settings.DEFAULT_CHAT_MODEL"]
        assert capability["provider_endpoints"] == ["https://openrouter.ai/api/v1/chat/completions"]
    assert functions["app.core.openrouter.create_openrouter_model"][
        "model_configuration_references"
    ] == ["settings.DEFAULT_CHAT_MODEL"]
