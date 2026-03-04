import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.messages import ModelMessagesTypeAdapter, ToolCallPart
from pydantic_ai.usage import UsageLimits

from app.config import settings
from app.clickhouse.client import query as ch_query

logger = logging.getLogger(__name__)


@dataclass
class FeasibilityDeps:
    """Runtime context injected into agent tools and system prompt."""

    price_keys: list[str] = field(default_factory=list)
    context_prompt: str = ""


# ── Pydantic models for mutation tool arguments ───────────────────────────────


class UnitConfig(BaseModel):
    type: str
    count: int = Field(ge=0)
    avgSizeSqm: float = Field(gt=0)


class BuildingUpdate(BaseModel):
    name: str
    floors: int = Field(ge=1)
    units: list[UnitConfig]


class AssumptionUpdate(BaseModel):
    # existing
    landCost: float | None = None
    buildCostPerSqm: float | None = None
    softCostsPct: float | None = None
    sellingCostsPct: float | None = None  # kept for backward compat, aliased on frontend
    financeRatePct: float | None = None
    constructionMonths: int | None = None
    salesLaunchMonth: int | None = None
    salesMonths: int | None = None
    # new
    agentCommissionPct: float | None = None
    marketingBudgetPct: float | None = None
    contingencyPct: float | None = None
    debtToCostRatio: float | None = None
    arrangementFeePct: float | None = None
    presaleDiscountPct: float | None = None
    priceEscalationPct: float | None = None
    targetROCPct: float | None = None


# ── Agent ─────────────────────────────────────────────────────────────────────

model = OpenAIChatModel(
    model_name=settings.DEFAULT_CHAT_MODEL,
    provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
)

agent = Agent(
    model,
    deps_type=FeasibilityDeps,
    model_settings={"temperature": 0.1},
    system_prompt=(
        "You are a Dubai real estate development feasibility assistant. "
        "You help developers analyse land plots, project configurations, and financial returns.\n\n"
        "## Tools available\n"
        "- `get_area_market_data` — fetch median price/sqm by unit type for any Dubai area\n"
        "- `search_projects` — find comparable projects by name\n"
        "- `get_project_data` — get building/unit breakdown for a specific project\n"
        "- `show_transactions` — display recent sale transactions in the Research panel (left sidebar)\n"
        "- `show_analytics` — display price trend and breakdown analytics in the Research panel\n"
        "- `update_prices` — propose updated selling price per sqm assumptions\n"
        "- `update_buildings` — propose a new building configuration\n"
        "- `update_assumptions` — propose changes to financial/timeline assumptions\n\n"
        "## When to use mutation tools\n"
        "When the user asks you to change prices, buildings, floors, unit mix, or any financial "
        "assumption — call the appropriate mutation tool. The user will see a preview and must "
        "approve before changes apply, so briefly state what you are proposing and why.\n\n"
        "## Formatting\n"
        "Use **bold** for key numbers, bullet lists for multiple items. No headers or tables. "
        "Use AED for currency.\n\n"
        "## Length\n"
        "Be brief. Match length to complexity — a simple question warrants one or two sentences. "
        "Never pad answers. Stop when the point is made."
    ),
)


@agent.system_prompt
async def inject_context(ctx: RunContext[FeasibilityDeps]) -> str:
    """Inject the current feasibility state as additional system context each turn."""
    return ctx.deps.context_prompt


# ── Market data tools (tool_plain — no RunContext needed) ─────────────────────


@agent.tool_plain
async def get_area_market_data(
    area: str, unit_type: str = "", days: int = 365
) -> dict[str, Any]:
    """Get median price per sqm for a Dubai area, optionally filtered by unit type."""
    if unit_type:
        sql = """
        SELECT
            rooms_en AS unit_type,
            count() AS txn_count,
            round(median(meter_sale_price), 0) AS median_price_sqm
        FROM ch_transactions
        WHERE area_name_en = {area:String}
          AND meter_sale_price > 0
          AND instance_date >= today() - {days:Int32}
          AND rooms_en = {unit_type:String}
        GROUP BY rooms_en
        ORDER BY txn_count DESC
        """
        params: dict[str, Any] = {"area": area, "days": days, "unit_type": unit_type}
    else:
        sql = """
        SELECT
            rooms_en AS unit_type,
            count() AS txn_count,
            round(median(meter_sale_price), 0) AS median_price_sqm
        FROM ch_transactions
        WHERE area_name_en = {area:String}
          AND meter_sale_price > 0
          AND instance_date >= today() - {days:Int32}
        GROUP BY rooms_en
        ORDER BY txn_count DESC
        """
        params = {"area": area, "days": days}
    try:
        rows = await ch_query(sql, params)
        return {"success": True, "area": area, "data": rows}
    except Exception as e:
        logger.exception("Error in get_area_market_data")
        return {"success": False, "error": str(e)}


@agent.tool_plain
async def search_projects(query_text: str) -> dict[str, Any]:
    """Search projects by name."""
    sql = """
    SELECT project_id, project_name_en, area_name_en, no_of_buildings, no_of_units
    FROM ch_projects
    WHERE project_name_en ILIKE {q:String}
      AND project_name_en != ''
    LIMIT 10
    """
    try:
        rows = await ch_query(sql, {"q": f"%{query_text}%"})
        return {"success": True, "projects": rows}
    except Exception as e:
        logger.exception("Error in search_projects")
        return {"success": False, "error": str(e)}


@agent.tool_plain
async def get_project_data(project_id: int) -> dict[str, Any]:
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
        b_rows = await ch_query(buildings_sql, {"pid": project_id})
        u_rows = await ch_query(units_sql, {"pid": project_id})
        return {
            "success": True,
            "project_id": project_id,
            "buildings": b_rows[0] if b_rows else {},
            "unit_mix": u_rows,
        }
    except Exception as e:
        logger.exception("Error in get_project_data")
        return {"success": False, "error": str(e)}


# ── Mutation tools ────────────────────────────────────────────────────────────


@agent.tool(docstring_format="google")
async def update_prices(
    ctx: RunContext[FeasibilityDeps], prices: dict[str, float]
) -> str:
    """Propose updated selling price per sqm assumptions by unit type (AED/sqm).

    Args:
        prices: mapping of unit type to price per sqm — keys must exactly match
                those shown in the current pricePerSqm context.
    """
    if ctx.deps.price_keys:
        invalid = [k for k in prices if k not in ctx.deps.price_keys]
        if invalid:
            return f"Invalid unit type keys. Valid keys are: {json.dumps(ctx.deps.price_keys)}."
    return f"Proposed price update for {len(prices)} unit type(s). Awaiting user approval."


@agent.tool_plain(docstring_format="google")
async def update_buildings(buildings: list[BuildingUpdate]) -> str:
    """Propose a new building configuration.

    Args:
        buildings: list of buildings, each with name, floors (≥1), and units
                   (each unit has type, count, avgSizeSqm).
    """
    return f"Proposed building update: {len(buildings)} building(s). Awaiting user approval."


@agent.tool_plain(docstring_format="google")
async def update_assumptions(assumptions: AssumptionUpdate) -> str:
    """Propose changes to financial or timeline assumptions.

    Args:
        assumptions: partial update — only include fields to change:
            landCost, buildCostPerSqm, softCostsPct, financeRatePct,
            constructionMonths, salesLaunchMonth, salesMonths,
            agentCommissionPct, marketingBudgetPct, contingencyPct,
            debtToCostRatio, arrangementFeePct, presaleDiscountPct,
            priceEscalationPct, targetROCPct.
    """
    changes = assumptions.model_dump(exclude_none=True)
    return f"Proposed assumption update for {len(changes)} parameter(s). Awaiting user approval."


# ── Research tools ────────────────────────────────────────────────────────────


@agent.tool_plain
async def show_transactions(
    area: str, unit_type: str = "", days: int = 365, limit: int = 50
) -> str:
    """Display recent sale transactions in the Research panel (left sidebar)."""
    subject = f"recent {unit_type} transactions in {area}" if unit_type else f"recent transactions in {area}"
    return f"Pulling up {subject} (last {days} days, up to {limit}) in the Research panel."


@agent.tool_plain
async def show_analytics(
    area: str = "", project_name: str = "", days: int = 365
) -> str:
    """Display price trend and breakdown analytics in the Research panel."""
    subject = project_name or area or "current area"
    return f"Pulling up price analytics for {subject} (last {days} days) in the Research panel."


# ── Research tool name → panel tab mapping ────────────────────────────────────

_RESEARCH_TOOLS = {
    "show_transactions": "transactions",
    "show_analytics": "analytics",
}


async def _resolve_area(area: str) -> str:
    """Resolve a free-text area name to the best-matching area_name_en in ch_transactions.

    Tries exact match first (highest priority), then falls back to the
    highest-volume ILIKE match. Returns the original string if nothing matches.
    """
    if not area:
        return area
    sql = """
    SELECT area_name_en
    FROM ch_transactions
    WHERE area_name_en ILIKE {pattern:String}
      AND trans_group_en = 'Sales' AND meter_sale_price > 0
    GROUP BY area_name_en
    ORDER BY (area_name_en = {area:String}) DESC, count() DESC
    LIMIT 1
    """
    try:
        rows = await ch_query(sql, {"area": area, "pattern": f"%{area}%"})
        return rows[0]["area_name_en"] if rows else area
    except Exception as e:
        logger.error("_resolve_area failed for %r: %s", area, e)
        return area


async def _fetch_research_payload(tool_name: str, args: dict) -> dict | None:
    """Execute ClickHouse queries for research tools and return panel data."""
    if tool_name == "show_transactions":
        area = args.get("area", "")
        unit_type = args.get("unit_type", "")
        days = args.get("days", 365)
        limit = min(args.get("limit", 50), 100)
        if area:
            area = await _resolve_area(area)
        where = ["trans_group_en = 'Sales'", "meter_sale_price > 0"]
        params: dict = {}
        if area:
            where.append("area_name_en = {area:String}")
            params["area"] = area
        if unit_type:
            where.append("rooms_en = {unit_type:String}")
            params["unit_type"] = unit_type
        if days:
            where.append("instance_date >= today() - {days:Int32}")
            params["days"] = days
        params["limit"] = limit
        sql = f"""
        SELECT transaction_id, instance_date, project_name_en, rooms_en,
               procedure_area, actual_worth, meter_sale_price, reg_type_en
        FROM ch_transactions
        WHERE {' AND '.join(where)}
        ORDER BY instance_date DESC
        LIMIT {{limit:Int32}}
        """
        try:
            rows = await ch_query(sql, params)
            return {
                "rows": rows,
                "filters": {"area": area, "unit_type": unit_type, "days": days},
                "count": len(rows),
            }
        except Exception as e:
            logger.error("show_transactions query failed: %s", e)
            return None

    elif tool_name == "show_analytics":
        area = args.get("area", "")
        project_name = args.get("project_name", "")
        days = args.get("days", 365)
        if area and not project_name:
            area = await _resolve_area(area)
        where = ["meter_sale_price > 0", "trans_group_en = 'Sales'"]
        params = {}
        if project_name:
            where.append("project_name_en = {project_name:String}")
            params["project_name"] = project_name
        elif area:
            where.append("area_name_en = {area:String}")
            params["area"] = area
        if days:
            where.append("instance_date >= today() - {days:Int32}")
            params["days"] = days
        where_clause = " AND ".join(where)
        trend_sql = f"""
        SELECT toStartOfMonth(instance_date) AS month,
               round(median(meter_sale_price), 0) AS median_price_sqm,
               count() AS txn_count
        FROM ch_transactions
        WHERE {where_clause}
        GROUP BY month ORDER BY month
        """
        rooms_sql = f"""
        SELECT rooms_en, count() AS txn_count,
               round(median(meter_sale_price), 0) AS median_price_sqm,
               round(avg(procedure_area), 0) AS avg_area_sqm
        FROM ch_transactions
        WHERE {where_clause}
        GROUP BY rooms_en ORDER BY txn_count DESC
        """
        try:
            trend_rows, rooms_rows = await asyncio.gather(
                ch_query(trend_sql, params),
                ch_query(rooms_sql, params),
            )
            return {
                "trend": trend_rows,
                "by_rooms": rooms_rows,
                "filters": {"area": area, "project_name": project_name, "days": days},
            }
        except Exception as e:
            logger.error("show_analytics query failed: %s", e)
            return None

    return None


# ── Tool name → SSE action mapping ───────────────────────────────────────────

_MUTATION_TOOLS = {
    "update_prices": "set_price_per_sqm",
    "update_buildings": "set_buildings",
    "update_assumptions": "set_assumptions",
}


def _extract_payload(part: ToolCallPart) -> Any:
    """Extract and validate the SSE payload from a mutation ToolCallPart."""
    args = part.args_as_dict()
    if part.tool_name == "update_prices":
        return args.get("prices", args)
    elif part.tool_name == "update_buildings":
        raw = args.get("buildings", args)
        try:
            return [
                {
                    **BuildingUpdate(**b).model_dump(),
                    "id": b.get("id") or str(uuid.uuid4()),
                }
                for b in raw
            ]
        except Exception:
            logger.error("Failed to validate building payload: %s", raw)
            return None
    elif part.tool_name == "update_assumptions":
        raw = args.get("assumptions", args)
        try:
            return AssumptionUpdate(**raw).model_dump(exclude_none=True)
        except Exception:
            return {k: v for k, v in raw.items() if v is not None}
    return None


async def stream_feasibility_response(
    messages: list[dict], context: dict, history_json: str | None = None
) -> AsyncGenerator[str, None]:
    """Stream feasibility chat response as SSE events, then emit pending mutation actions."""
    area = context.get("area", "Unknown")
    plot = context.get("plot")
    plot_info = f"{plot['actual_area']} sqm in {area}" if plot else area
    cfg = context.get("config", {})
    assumptions = context.get("assumptions", {})
    derived = context.get("derived", {})

    price_keys = list(cfg.get("pricePerSqm", {}).keys())

    context_prompt = (
        f"## Current feasibility context\n"
        f"- Area: {area}\n"
        f"- Plot: {plot_info}\n\n"
        f"### Building configuration\n"
        f"{json.dumps(cfg.get('buildings', []), indent=2)}\n\n"
        f"### Price assumptions (AED/sqm)\n"
        f"{json.dumps(cfg.get('pricePerSqm', {}))}\n\n"
        f"### Financial & timeline assumptions\n"
        f"{json.dumps(assumptions, indent=2)}\n\n"
        f"### Key financials (read-only)\n"
        f"GDV: {derived.get('totalGDV', 0):,} AED | "
        f"Net Revenue: {derived.get('netRevenue', 0):,} AED | "
        f"Total cost: {derived.get('totalDevCost', 0):,} AED | "
        f"Equity: {derived.get('equityRequired', 0):,} AED | "
        f"Debt: {derived.get('debtAmount', 0):,} AED | "
        f"Profit: {derived.get('grossProfit', 0):,} AED | "
        f"ROC: {derived.get('returnOnCost', 0)}% | "
        f"ROE: {derived.get('returnOnEquity', 0)}% | "
        f"Equity Multiple: {derived.get('equityMultiple', 0)}x | "
        f"Unlevered IRR: {derived.get('unleveredIRR', 'N/A')}% | "
        f"Levered IRR: {derived.get('leveredIRR', 'N/A')}%\n"
    )

    deps = FeasibilityDeps(price_keys=price_keys, context_prompt=context_prompt)

    # Lossless history when available; start fresh if missing or corrupt
    history: list = []
    if history_json:
        try:
            history = ModelMessagesTypeAdapter.validate_json(history_json)
        except Exception as e:
            logger.error("Failed to deserialize history_json: %s — starting fresh", e)
            yield f"data: {json.dumps({'type': 'warning', 'content': 'Session context reset — conversation history could not be restored.'})}\n\n"

    user_turns = [m for m in messages if m.get("role") == "user"]
    user_message = user_turns[-1].get("content", "") if user_turns else ""

    try:
        async with agent.iter(
            user_message, message_history=history, deps=deps,
            usage_limits=UsageLimits(request_limit=10),
        ) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as stream:
                        async for chunk in stream.stream_text(
                            delta=True, debounce_by=0.01
                        ):
                            yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"
                elif Agent.is_call_tools_node(node):
                    for part in node.model_response.parts:
                        if not isinstance(part, ToolCallPart):
                            continue
                        if part.tool_name in _MUTATION_TOOLS:
                            action = _MUTATION_TOOLS[part.tool_name]
                            payload = _extract_payload(part)
                            if payload is not None:
                                yield f"data: {json.dumps({'type': 'pending_action', 'action': action, 'payload': payload}, default=str)}\n\n"
                        elif part.tool_name in _RESEARCH_TOOLS:
                            tab = _RESEARCH_TOOLS[part.tool_name]
                            payload = await _fetch_research_payload(part.tool_name, part.args_as_dict())
                            if payload is not None:
                                yield f"data: {json.dumps({'type': 'show_research', 'tab': tab, 'data': payload}, default=str)}\n\n"

            new_msgs = run.new_messages_json().decode()
            yield f"data: {json.dumps({'type': 'done', 'new_messages_json': new_msgs})}\n\n"

    except Exception as e:
        logger.exception("Error in feasibility chat stream")
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
