"""The CRM Operations Assistant lives in app/crm/assistant/ and is CRM-only.

Market AI (/chat: DXB sales, rents, pricing, comparables, listing research) is a separate
product in app/market_ai/. The CRM assistant registers no market workflow, streams from its own
endpoint, and shares only the generic conversation API (app/chat/router.py) behind sign-in.
"""

import importlib

import pytest
from fastapi.routing import APIRoute


def test_the_package_exports_its_crm_reads_and_modules():
    from app.crm import assistant
    from app.crm.assistant import (
        agent,
        capabilities,
        connector_tools,
        crm_tools,
        dependencies,
        models,
        records,
        repository,
        router,
        routing,
        service,
        workflows,
    )

    assert assistant.query_my_records is records.query_my_records
    assert assistant.has_current_access is records.has_current_access
    assert assistant.same_team is records.same_team
    for module in (
        agent,
        capabilities,
        connector_tools,
        crm_tools,
        dependencies,
        models,
        repository,
        router,
        routing,
        service,
        workflows,
    ):
        assert module.__name__.startswith("app.crm.assistant.")


@pytest.mark.parametrize(
    "module",
    [
        # Market AI moved to app.market_ai; CRM modules to app.crm.assistant.
        "app.chat.tools",
        "app.chat.artifacts",
        "app.chat.agent",
        "app.chat.workflows",
        "app.chat.routing",
        "app.crm.assistant_models",
        "app.crm.assistant_repository",
    ],
)
def test_old_mixed_chat_locations_are_gone(module):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module)


def test_the_assistant_has_crm_workflows_only():
    from app.crm.assistant import routing, workflows
    from app.crm.assistant.agent import agent

    assert set(agent._function_toolset.tools) == {
        "retrieve_personal_crm",
        "plan_followups",
        "prepare_action",
    }
    assert set(routing.Workflow.__args__) == {"crm", "followup", "action"}
    for name in ("market_agent", "pricing_agent", "research_market", "analyze_pricing"):
        assert not hasattr(workflows, name), name
    specialists = (workflows.crm_agent, workflows.followup_agent, workflows.action_agent)
    tools = {tool for agent in specialists for tool in agent._function_toolset.tools}
    market = {
        "query_market_metrics",
        "get_market_pulse",
        "rank_areas",
        "comparable_evidence",
        "research_listing_shortlist",
        "get_listing_inventory",
        "get_project_profile",
    }
    assert not tools & market


def test_each_product_streams_from_its_own_endpoint_over_one_shared_conversation_api():
    from app.main import app

    routes = {
        (method, route.path): route.endpoint.__module__
        for route in app.routes
        if isinstance(route, APIRoute) and "chat" in route.path
        for method in route.methods
    }
    stream = "/conversations/{conversation_id}/messages/stream"
    assert routes[("POST", "/api/v1/chat" + stream)] == "app.crm.assistant.router"
    assert routes[("POST", "/api/v1/market-chat" + stream)] == "app.market_ai.router"
    shared = {key: module for key, module in routes.items() if "stream" not in key[1]}
    assert shared and set(shared.values()) <= {"app.chat.router", "app.feasibility.router"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/chat/conversations"),
        ("post", "/api/v1/chat/conversations/1/messages/stream"),
        ("post", "/api/v1/market-chat/conversations/1/messages/stream"),
    ],
)
async def test_the_chat_api_requires_sign_in(client_no_auth, method, path):
    request = getattr(client_no_auth, method)
    response = await (request(path) if method == "get" else request(path, json={"message": "hi"}))
    assert response.status_code in {401, 403}
