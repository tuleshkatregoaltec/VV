import json
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock

from app.chat.agent import agent
from app.chat.mcp import ChatToolContext, market_mcp


async def test_runtime_chat_exposes_only_authenticated_mcp_capabilities():
    # Local functions must not silently bypass MCP evidence and authorization.
    assert agent._function_toolset.tools == {}
    context = ChatToolContext("owner", "org", date(2026, 10, 3), "schema-test")
    async with market_mcp(context, AsyncMock(return_value=True)) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == {
        "query_market_metrics",
        "get_listing_inventory",
        "get_project_delivery_summary",
        "compare_listing_age",
        "compare_listing_rents",
        "compose_market_report",
    }
    expected = json.loads((Path(__file__).parent / "fixtures/chat_tools.json").read_text())
    actual = {
        tool.name: {"description": tool.description, "schema": tool.inputSchema} for tool in tools
    }
    assert actual == expected
