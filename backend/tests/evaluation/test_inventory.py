from scripts.evaluations.market_ai.inventory import build_inventory


def test_actual_chat_registration_links_to_public_capabilities_and_warehouse():
    inventory = build_inventory()
    chat = next(
        agent for agent in inventory["agents"] if agent["id"] == "app.market_ai.agent.agent"
    )
    assert {tool["function"] for tool in chat["tools"]} == {
        "app.market_ai.workflows.research_market",
        "app.market_ai.workflows.analyze_pricing",
    }
    # CRM tools remain registered only on the separate CRM Operations Assistant.
    specialists = [
        item
        for item in inventory["agents"]
        if item["id"].startswith(("app.market_ai.workflows.", "app.crm.assistant.workflows."))
    ]
    registered = {tool["function"] for item in specialists for tool in item["tools"]}
    assert {
        "app.market_ai.tools.query_market_metrics",
        "app.crm.assistant.crm_tools.query_my_crm_records",
        "app.crm.assistant.workflows.propose_crm_action",
        "app.market_ai.tools.research_listing_shortlist",
        "app.market_ai.tools.comparable_evidence",
        "app.market_ai.tools.compare_stored_projects",
    } <= registered
    assert all("confirm" not in name for name in registered)
    pulse = inventory["functions"]["app.analytics.queries.fetch_market_pulse"]
    # Chat's market pulse reads the Analytics DXBI records (an imported source expression the
    # inventory does not resolve), no longer the combined market layer.
    from app.analytics import dxbi, queries

    assert "ch_transactions" not in pulse["sql_source_candidates"]
    assert dxbi.SALES_SOURCE in queries.GET_MARKET_PULSE_SQL


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


def test_interpolated_sql_source_is_unknown_instead_of_a_where_table(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "queries.py").write_text(
        'from somewhere import SOURCE\nfrom app.clickhouse.client import query\nasync def fetch():\n    return await query(f"SELECT * FROM {SOURCE} WHERE active = 1")\n'
    )
    assert build_inventory(app)["functions"]["app.queries.fetch"]["sql_source_candidates"] == []
