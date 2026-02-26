import json
import logging
import secrets
from typing import Any, AsyncGenerator

from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart, TextPart, ToolCallPart

from app.config import settings
from app.clickhouse.client import query

logger = logging.getLogger(__name__)

model = OpenAIChatModel(
    model_name=settings.DEFAULT_CHAT_MODEL,
    provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
)

agent = Agent(
    model,
    system_prompt=(
        "You are a Dubai real estate development feasibility assistant. "
        "You help developers analyse land plots, project configurations, and financial returns.\n\n"
        "## Tools available\n"
        "- `get_area_market_data` — fetch median price/sqm by unit type for any Dubai area\n"
        "- `search_projects` — find comparable projects by name\n"
        "- `get_project_data` — get building/unit breakdown for a specific project\n"
        "- `update_prices` — update the selling price per sqm assumptions on the user's project\n"
        "- `update_buildings` — replace the building configuration on the user's project\n\n"
        "## When to use mutation tools\n"
        "When the user asks you to change prices, buildings, floors, or unit mix — call the "
        "appropriate mutation tool (`update_prices` or `update_buildings`) in addition to explaining "
        "your reasoning. The tool call will instantly update the numbers on screen.\n\n"
        "## Formatting\n"
        "Use **bold** for key numbers, bullet lists for multiple items. No headers or tables. "
        "Keep responses concise. Use AED for currency."
    ),
)


# ── Market data tools ─────────────────────────────────────────────────────────

@agent.tool
async def get_area_market_data(
    ctx: RunContext[None], area: str, unit_type: str = "", days: int = 365
) -> dict[str, Any]:
    """Get median price per sqm for a Dubai area, optionally filtered by unit type."""
    params: dict[str, Any] = {"area": area, "days": days}
    type_filter = ""
    if unit_type:
        type_filter = "AND rooms_en = {unit_type:String}"
        params["unit_type"] = unit_type

    sql = f"""
    SELECT
        rooms_en AS unit_type,
        count() AS txn_count,
        round(median(meter_sale_price), 0) AS median_price_sqm
    FROM ch_transactions
    WHERE area_name_en = {{area:String}}
      AND meter_sale_price > 0
      AND instance_date >= today() - {{days:Int32}}
      {type_filter}
    GROUP BY rooms_en
    ORDER BY txn_count DESC
    """
    try:
        rows = await query(sql, params)
        return {"success": True, "area": area, "data": rows}
    except Exception as e:
        logger.exception(f"Error in get_area_market_data: {e}")
        return {"success": False, "error": str(e)}


@agent.tool
async def search_projects(ctx: RunContext[None], query_text: str) -> dict[str, Any]:
    """Search projects by name."""
    sql = """
    SELECT project_id, project_name_en, area_name_en, no_of_buildings, no_of_units
    FROM ch_projects
    WHERE project_name_en ILIKE {q:String}
      AND project_name_en != ''
    LIMIT 10
    """
    try:
        rows = await query(sql, {"q": f"%{query_text}%"})
        return {"success": True, "projects": rows}
    except Exception as e:
        logger.exception(f"Error in search_projects: {e}")
        return {"success": False, "error": str(e)}


@agent.tool
async def get_project_data(ctx: RunContext[None], project_id: int) -> dict[str, Any]:
    """Get building count, floor count and unit mix for a project."""
    buildings_sql = """
    SELECT count() AS cnt, avg(floors) AS avg_floors
    FROM ch_buildings WHERE project_id = {pid:Int32}
    """
    units_sql = """
    SELECT rooms_en, count() AS cnt, round(avg(actual_area), 1) AS avg_area
    FROM ch_units
    WHERE project_id = {pid:Int32} AND rooms_en != ''
    GROUP BY rooms_en
    """
    try:
        b_rows = await query(buildings_sql, {"pid": project_id})
        u_rows = await query(units_sql, {"pid": project_id})
        return {
            "success": True,
            "project_id": project_id,
            "buildings": b_rows[0] if b_rows else {},
            "unit_mix": u_rows,
        }
    except Exception as e:
        logger.exception(f"Error in get_project_data: {e}")
        return {"success": False, "error": str(e)}


# ── Mutation tools (update frontend state) ───────────────────────────────────

@agent.tool
async def update_prices(
    ctx: RunContext[None], prices: dict[str, float]
) -> str:
    """Update selling price per sqm assumptions by unit type (AED/sqm).

    Args:
        prices: mapping of unit type to price per sqm, e.g. {"Studio": 18000, "1BR": 20000}
    """
    return f"Price assumptions updated for {len(prices)} unit types."


@agent.tool
async def update_buildings(
    ctx: RunContext[None],
    buildings: list[dict[str, Any]],
) -> str:
    """Replace the building configuration.

    Args:
        buildings: list of buildings, each with:
            - name (str)
            - floors (int)
            - units: list of {type: str, count: int, avgSizeSqm: float}
    """
    return f"Building configuration updated: {len(buildings)} building(s)."


# ── Tool name → SSE action mapping ───────────────────────────────────────────

_MUTATION_TOOLS = {
    "update_prices": "set_price_per_sqm",
    "update_buildings": "set_buildings",
}


async def stream_feasibility_response(
    messages: list[dict], context: dict
) -> AsyncGenerator[str, None]:
    """Stream feasibility chat response as SSE events, then emit any mutation tool calls."""
    area = context.get("area", "Unknown")
    plot = context.get("plot")
    plot_info = f"{plot['actual_area']} sqm in {area}" if plot else area
    buildings = context.get("config", {}).get("buildings", [])

    context_prompt = (
        f"Current feasibility context:\n"
        f"- Area: {area}\n"
        f"- Plot: {plot_info}\n"
        f"- Buildings: {json.dumps(buildings)}\n"
        f"- Price assumptions (AED/sqm): {context.get('config', {}).get('pricePerSqm', {})}\n"
    )

    history = []
    for msg in messages[:-1]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=content)]))
        elif role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=content)]))

    user_message = messages[-1].get("content", "") if messages else ""
    full_prompt = f"{context_prompt}\n\nUser: {user_message}"

    try:
        async with agent.run_stream(full_prompt, message_history=history) as result:
            async for chunk in result.stream_text(delta=True, debounce_by=0.01):
                yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

        # After streaming completes, emit any mutation tool calls as action events
        for msg in result.all_messages():
            for part in getattr(msg, "parts", []):
                if not isinstance(part, ToolCallPart):
                    continue
                action = _MUTATION_TOOLS.get(part.tool_name)
                if not action:
                    continue
                args = part.args_as_dict()

                if part.tool_name == "update_prices":
                    payload = args.get("prices", args)
                elif part.tool_name == "update_buildings":
                    raw = args.get("buildings", args)
                    # Ensure every building has an id
                    payload = [
                        {**b, "id": b.get("id") or secrets.token_urlsafe(8)}
                        for b in raw
                    ]
                else:
                    payload = args

                yield f"data: {json.dumps({'type': 'action', 'action': action, 'payload': payload})}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    except Exception as e:
        logger.exception("Error in feasibility chat stream")
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
