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
from app.feasibility.normalization import (
    Stage,
    Usage,
    transaction_stage_clause,
    transaction_usage_clause,
)
from app.feasibility.models import HBUProductOption, HBUStudy, HBUUnitRecommendation
from app.feasibility.service import (
    get_gis_plot_dossier,
    get_land_sale_evidence,
    get_market_pricing,
    rank_plot_comparables,
)

logger = logging.getLogger(__name__)


@dataclass
class FeasibilityDeps:
    """Runtime context injected into agent tools and system prompt."""

    price_keys: list[str] = field(default_factory=list)
    context_prompt: str = ""
    current_plot_number: str | None = None
    current_area: str | None = None


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
    sellingCostsPct: float | None = (
        None  # kept for backward compat, aliased on frontend
    )
    financeRatePct: float | None = None
    constructionMonths: int | None = None
    salesLaunchMonth: int | None = None
    salesMonths: int | None = None
    agentCommissionPct: float | None = None
    marketingBudgetPct: float | None = None
    contingencyPct: float | None = None
    debtToCostRatio: float | None = None
    arrangementFeePct: float | None = None
    presaleDiscountPct: float | None = None
    priceEscalationPct: float | None = None
    targetROCPct: float | None = None
    # Phase 2 — site & areas
    siteAreaSqm: float | None = None
    plotRatioFAR: float | None = None
    lossFactorGFAtoNSA: float | None = None
    hasDemolition: bool | None = None
    hasAncillaryRetail: bool | None = None
    # Phase 3 — absolute cost line items (AED)
    infrastructureCostAED: float | None = None
    authorityConnectionFeesAED: float | None = None
    communityMasterDevFeesAED: float | None = None
    demolitionCostAED: float | None = None
    designSupervisionAED: float | None = None
    projectMgmtAED: float | None = None
    otherProfessionalFeesAED: float | None = None
    marketingLaunchAED: float | None = None
    midPointInflationPct: float | None = None
    vatRateOnCostsPct: float | None = None
    vatRecoveryPct: float | None = None
    corporateTaxRatePct: float | None = None


class AgentHBUStudyDraft(BaseModel):
    headline: str
    summary: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    product_options: list[HBUProductOption] = Field(default_factory=list)
    recommended_mix: list[HBUUnitRecommendation] = Field(default_factory=list)
    price_per_sqm_by_type: dict[str, float] = Field(default_factory=dict)
    assumptions_patch: dict[str, float | bool | str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


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
        "- `get_current_plot_dossier` — inspect the selected GIS plot constraints and restrictions\n"
        "- `get_area_market_data` — fetch segmented median price/sqm by unit type for an area\n"
        "- `search_projects` — find comparable projects by name\n"
        "- `get_project_data` — get building/unit breakdown for a specific project\n"
        "- `rank_pricing_comparables` — rank existing pricing comparables for the selected plot\n"
        "- `rank_pipeline_comparables` — rank upcoming competition comparables for the selected plot\n"
        "- `get_land_sale_evidence_for_plot` — fetch nearby land sale evidence for the selected plot area\n"
        "- `draft_hbu_study` — prepare an agent-authored first-pass HBU study for the selected plot\n"
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

hbu_study_agent = Agent(
    model,
    output_type=AgentHBUStudyDraft,
    model_settings={"temperature": 0.1},
    system_prompt=(
        "You are producing an initial Dubai highest-and-best-use study for a single land plot.\n\n"
        "You will be given a GIS plot dossier, market pricing evidence, pricing comparables, and pipeline comparables. "
        "Your job is to make a grounded, conservative recommendation. Do not use any scoring formula. "
        "Reason from the evidence and the hard plot constraints.\n\n"
        "Rules:\n"
        "- Treat GIS zoning, GFA, height, coverage, notes, and warnings as hard constraints.\n"
        "- Prefer a narrower, more plausible recommendation over an aggressive one.\n"
        "- If evidence is weak or mixed, say so in `warnings` and simplify the recommendation.\n"
        "- Do not recommend more than 4 unit types.\n"
        "- `recommended_mix.share_pct` should sum to about 100.\n"
        "- `suggested_units` must be plausible for the plot's max GFA and average unit sizes.\n"
        "- `price_per_sqm_by_type` must align with the recommended mix and the evidence provided.\n"
        "- `assumptions_patch` should only contain a small set of useful seed assumptions, not a full financial model.\n"
        "- Keep the language direct. No hype.\n"
    ),
)


@agent.system_prompt
async def inject_context(ctx: RunContext[FeasibilityDeps]) -> str:
    """Inject the current feasibility state as additional system context each turn."""
    return ctx.deps.context_prompt


# ── Market data tools (tool_plain — no RunContext needed) ─────────────────────


@agent.tool
async def get_current_plot_dossier(
    ctx: RunContext[FeasibilityDeps],
) -> dict[str, Any]:
    """Get the current GIS plot dossier from feasibility context."""
    plot_number = ctx.deps.current_plot_number
    if not plot_number:
        return {
            "success": False,
            "error": "No plot is selected in the current feasibility context.",
        }
    dossier = await get_gis_plot_dossier(plot_number)
    return {
        "success": dossier is not None,
        "plot": dossier.model_dump() if dossier else None,
    }


@agent.tool_plain
async def get_area_market_data(
    area: str, usage: Usage = "residential", stage: Stage = "existing", days: int = 365
) -> dict[str, Any]:
    """Get segmented median price per sqm for a Dubai area."""
    sql = f"""
    SELECT area_name_en
    FROM ch_transactions
    WHERE trans_group_en = 'Sales'
      AND area_name_en ILIKE {{pattern:String}}
    GROUP BY area_name_en
    ORDER BY (lower(area_name_en) = lower({{area:String}})) DESC, count() DESC
    LIMIT 1
    """
    try:
        resolved = await ch_query(sql, {"area": area, "pattern": f"%{area}%"})
        resolved_area = resolved[0]["area_name_en"] if resolved else area
        rows = await get_market_pricing(
            resolved_area, usage=usage, stage=stage, days=days
        )
        return {
            "success": True,
            "area": resolved_area,
            "usage": usage,
            "stage": stage,
            "data": [row.model_dump() for row in rows],
        }
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


@agent.tool
async def rank_pricing_comparables(
    ctx: RunContext[FeasibilityDeps], usage: Usage = "residential", limit: int = 5
) -> dict[str, Any]:
    """Rank pricing comparables for the selected GIS plot."""
    plot_number = ctx.deps.current_plot_number
    if not plot_number:
        return {
            "success": False,
            "error": "No plot is selected in the current feasibility context.",
        }
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        return {"success": False, "error": f"GIS plot {plot_number} was not found."}
    comps = await rank_plot_comparables(
        dossier, usage=usage, comparison_type="pricing", limit=limit
    )
    return {
        "success": True,
        "plot_number": plot_number,
        "comparables": [c.model_dump() for c in comps],
    }


@agent.tool
async def rank_pipeline_comparables(
    ctx: RunContext[FeasibilityDeps], usage: Usage = "residential", limit: int = 5
) -> dict[str, Any]:
    """Rank upcoming competition comparables for the selected GIS plot."""
    plot_number = ctx.deps.current_plot_number
    if not plot_number:
        return {
            "success": False,
            "error": "No plot is selected in the current feasibility context.",
        }
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        return {"success": False, "error": f"GIS plot {plot_number} was not found."}
    comps = await rank_plot_comparables(
        dossier, usage=usage, comparison_type="pipeline", limit=limit
    )
    return {
        "success": True,
        "plot_number": plot_number,
        "comparables": [c.model_dump() for c in comps],
    }


@agent.tool
async def get_land_sale_evidence_for_plot(
    ctx: RunContext[FeasibilityDeps], days: int = 1825, limit: int = 12
) -> dict[str, Any]:
    """Get recent land sale evidence for the selected GIS plot area."""
    plot_number = ctx.deps.current_plot_number
    if not plot_number:
        return {
            "success": False,
            "error": "No plot is selected in the current feasibility context.",
        }
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        return {"success": False, "error": f"GIS plot {plot_number} was not found."}
    rows = await get_land_sale_evidence(
        area_name=dossier.community_name,
        plot_area_sqm=dossier.plot_area_sqm,
        days=days,
        limit=limit,
    )
    return {
        "success": True,
        "plot_number": plot_number,
        "area": dossier.community_name,
        "land_sales": [row.model_dump() for row in rows],
    }


@agent.tool
async def draft_hbu_study(
    ctx: RunContext[FeasibilityDeps], usage_override: Usage | None = None
) -> dict[str, Any]:
    """Draft an initial agent-authored HBU study for the selected GIS plot."""
    plot_number = ctx.deps.current_plot_number
    if not plot_number:
        return {
            "success": False,
            "error": "No plot is selected in the current feasibility context.",
        }
    study = await generate_agent_hbu_study(plot_number, usage_override=usage_override)
    return {
        "success": study is not None,
        "study": study.model_dump() if study else None,
    }


def _coerce_usage(value: str | None) -> Usage:
    if value in ("residential", "commercial", "mixed_use", "unknown"):
        return value
    return "unknown"


def _sanitize_agent_mix(
    dossier: Any,
    usage: Usage,
    draft: AgentHBUStudyDraft,
    market_pricing: list[Any],
) -> AgentHBUStudyDraft:
    rows = [
        row.model_copy(deep=True)
        for row in draft.recommended_mix
        if row.share_pct > 0 and row.avg_size_sqm > 0
    ]
    if not rows:
        return draft

    total_share = sum(row.share_pct for row in rows) or 100
    for row in rows:
        row.share_pct = round((row.share_pct / total_share) * 100, 1)

    if rows:
        share_delta = round(100 - sum(row.share_pct for row in rows), 1)
        rows[0].share_pct = round(rows[0].share_pct + share_delta, 1)

    pricing_by_type = {
        row.unit_type: float(row.median_price_sqm) for row in market_pricing
    }
    fallback_price = (
        round(sum(pricing_by_type.values()) / len(pricing_by_type), 0)
        if pricing_by_type
        else (15000.0 if usage != "commercial" else 11000.0)
    )

    nsa_efficiency = 1 - (
        float(draft.assumptions_patch.get("lossFactorGFAtoNSA", 15)) / 100
    )
    max_sellable_area = (
        dossier.max_gfa_sqm * nsa_efficiency
        if dossier.max_gfa_sqm > 0
        else dossier.plot_area_sqm
    )
    planned_sellable_area = sum(
        max(row.suggested_units, 0) * row.avg_size_sqm for row in rows
    )
    if max_sellable_area > 0 and planned_sellable_area > max_sellable_area * 1.05:
        scale = max_sellable_area / planned_sellable_area
        for row in rows:
            row.suggested_units = max(1, int(round(row.suggested_units * scale)))

    normalized_prices = dict(draft.price_per_sqm_by_type)
    for row in rows:
        price = (
            normalized_prices.get(row.unit_type)
            or pricing_by_type.get(row.unit_type)
            or row.price_sqm
            or fallback_price
        )
        row.price_sqm = round(float(price), 0)
        normalized_prices[row.unit_type] = row.price_sqm

    draft.recommended_mix = rows[:4]
    draft.price_per_sqm_by_type = {
        key: value
        for key, value in normalized_prices.items()
        if key in {row.unit_type for row in draft.recommended_mix}
    }
    return draft


async def generate_agent_hbu_study(
    plot_number: str, usage_override: Usage | None = None
) -> HBUStudy | None:
    dossier = await get_gis_plot_dossier(plot_number)
    if dossier is None:
        return None

    usage = usage_override or dossier.inferred_usage
    market_area = dossier.community_name
    market_pricing = await get_market_pricing(market_area, usage, stage="existing")
    pricing_evidence = await rank_plot_comparables(dossier, usage, "pricing")
    competition_evidence = await rank_plot_comparables(dossier, usage, "pipeline")
    land_sales_evidence = await get_land_sale_evidence(
        area_name=dossier.community_name,
        plot_area_sqm=dossier.plot_area_sqm,
        days=1825,
        limit=12,
    )

    prompt = (
        f"Prepare an initial HBU study for plot {dossier.plot_number}.\n\n"
        f"Usage to evaluate: {usage}\n"
        f"Market area: {market_area}\n\n"
        f"GIS plot dossier:\n{dossier.model_dump_json(indent=2)}\n\n"
        f"Market pricing evidence:\n{json.dumps([row.model_dump() for row in market_pricing], indent=2)}\n\n"
        f"Pricing comparables:\n{json.dumps([row.model_dump() for row in pricing_evidence], indent=2)}\n\n"
        f"Pipeline comparables:\n{json.dumps([row.model_dump() for row in competition_evidence], indent=2)}\n\n"
        f"Land sale evidence:\n{json.dumps([row.model_dump() for row in land_sales_evidence], indent=2)}\n\n"
        "Return a conservative, evidence-based initial HBU study. "
        "Do not force a full-program mix if the evidence is thin. "
        "Keep assumptions modest and point out uncertainty. "
        "Use the land sale evidence to anchor a realistic land-cost view when the evidence is relevant."
    )

    result = await hbu_study_agent.run(prompt)
    draft = _sanitize_agent_mix(dossier, usage, result.output, market_pricing)

    warnings = list(dossier.warnings)
    warnings.extend(item for item in draft.warnings if item not in warnings)
    if not market_pricing:
        warnings.append(
            "No segmented existing transaction pricing was found for this GIS community name."
        )

    return HBUStudy(
        plot_number=dossier.plot_number,
        usage=_coerce_usage(usage),
        market_area=market_area,
        headline=draft.headline,
        summary=draft.summary,
        constraints=draft.constraints,
        pricing_evidence=pricing_evidence,
        competition_evidence=competition_evidence,
        land_sales_evidence=land_sales_evidence,
        market_pricing=market_pricing,
        product_options=draft.product_options,
        recommended_mix=draft.recommended_mix,
        price_per_sqm_by_type=draft.price_per_sqm_by_type,
        assumptions_patch=draft.assumptions_patch,
        warnings=warnings,
    )


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
    return (
        f"Proposed price update for {len(prices)} unit type(s). Awaiting user approval."
    )


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
            priceEscalationPct, targetROCPct,
            siteAreaSqm, plotRatioFAR, lossFactorGFAtoNSA,
            hasDemolition, hasAncillaryRetail,
            infrastructureCostAED, authorityConnectionFeesAED,
            communityMasterDevFeesAED, demolitionCostAED,
            designSupervisionAED, projectMgmtAED, otherProfessionalFeesAED,
            marketingLaunchAED, midPointInflationPct,
            vatRateOnCostsPct, vatRecoveryPct, corporateTaxRatePct.
    """
    changes = assumptions.model_dump(exclude_none=True)
    return f"Proposed assumption update for {len(changes)} parameter(s). Awaiting user approval."


# ── Research tools ────────────────────────────────────────────────────────────


@agent.tool_plain
async def show_transactions(
    area: str,
    unit_type: str = "",
    usage: Usage = "residential",
    stage: Stage = "existing",
    days: int = 365,
    limit: int = 50,
) -> str:
    """Display recent sale transactions in the Research panel (left sidebar)."""
    subject = (
        f"recent {unit_type} transactions in {area}"
        if unit_type
        else f"recent transactions in {area}"
    )
    return f"Pulling up {subject} ({usage}, {stage}, last {days} days, up to {limit}) in the Research panel."


@agent.tool_plain
async def show_analytics(
    area: str = "",
    project_name: str = "",
    usage: Usage = "residential",
    stage: Stage = "existing",
    days: int = 365,
) -> str:
    """Display price trend and breakdown analytics in the Research panel."""
    subject = project_name or area or "current area"
    return f"Pulling up price analytics for {subject} ({usage}, {stage}, last {days} days) in the Research panel."


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
        usage = args.get("usage", "residential")
        stage = args.get("stage", "existing")
        days = args.get("days", 365)
        limit = min(args.get("limit", 50), 100)
        if area:
            area = await _resolve_area(area)
        where = [
            "trans_group_en = 'Sales'",
            "meter_sale_price > 0",
            transaction_usage_clause(usage),
            transaction_stage_clause(stage),
        ]
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
        WHERE {" AND ".join(where)}
        ORDER BY instance_date DESC
        LIMIT {{limit:Int32}}
        """
        try:
            rows = await ch_query(sql, params)
            return {
                "rows": rows,
                "filters": {
                    "area": area,
                    "unit_type": unit_type,
                    "usage": usage,
                    "stage": stage,
                    "days": days,
                },
                "count": len(rows),
            }
        except Exception as e:
            logger.error("show_transactions query failed: %s", e)
            return None

    elif tool_name == "show_analytics":
        area = args.get("area", "")
        project_name = args.get("project_name", "")
        usage = args.get("usage", "residential")
        stage = args.get("stage", "existing")
        days = args.get("days", 365)
        if area and not project_name:
            area = await _resolve_area(area)
        where = [
            "meter_sale_price > 0",
            "trans_group_en = 'Sales'",
            transaction_usage_clause(usage),
            transaction_stage_clause(stage),
        ]
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
                "filters": {
                    "area": area,
                    "project_name": project_name,
                    "usage": usage,
                    "stage": stage,
                    "days": days,
                },
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
    plot_dossier = context.get("plotDossier")
    hbu_study = context.get("hbuStudy")
    plot_area = None
    if isinstance(plot, dict):
        plot_area = plot.get("plot_area_sqm") or plot.get("actual_area")
    plot_info = f"{plot_area} sqm in {area}" if plot_area else area
    cfg = context.get("config", {})
    assumptions = context.get("assumptions", {})
    derived = context.get("derived", {})

    price_keys = list(cfg.get("pricePerSqm", {}).keys())
    current_plot_number = (
        plot.get("plot_number")
        if isinstance(plot, dict)
        else plot_dossier.get("plot_number")
        if isinstance(plot_dossier, dict)
        else None
    )

    context_prompt = (
        f"## Current feasibility context\n"
        f"- Area: {area}\n"
        f"- Plot: {plot_info}\n\n"
        f"### Plot dossier\n"
        f"{json.dumps(plot_dossier, indent=2)}\n\n"
        f"### Initial HBU study\n"
        f"{json.dumps(hbu_study, indent=2)}\n\n"
        f"### Building configuration\n"
        f"{json.dumps(cfg.get('buildings', []), indent=2)}\n\n"
        f"### Price assumptions (AED/sqm)\n"
        f"{json.dumps(cfg.get('pricePerSqm', {}))}\n\n"
        f"### Financial & timeline assumptions\n"
        f"{json.dumps(assumptions, indent=2)}\n\n"
        f"### Key financials (read-only)\n"
        f"GDV: {derived.get('totalGDV', 0):,} AED | "
        f"Net Revenue: {derived.get('netRevenue', 0):,} AED | "
        f"Hard costs: {derived.get('totalHardCost', 0):,} AED | "
        f"Soft costs: {derived.get('totalSoftCost', 0):,} AED | "
        f"Infrastructure: {derived.get('totalInfrastructureCost', 0):,} AED | "
        f"Professional fees: {derived.get('totalProfessionalFees', 0):,} AED | "
        f"Inflation on costs: {derived.get('inflationOnCosts', 0):,} AED | "
        f"Total cost: {derived.get('totalDevCost', 0):,} AED | "
        f"Equity: {derived.get('equityRequired', 0):,} AED | "
        f"Debt: {derived.get('debtAmount', 0):,} AED | "
        f"Gross profit: {derived.get('grossProfit', 0):,} AED | "
        f"Corp tax: {derived.get('corporateTaxProvision', 0):,} AED | "
        f"Net profit: {derived.get('netProfit', 0):,} AED | "
        f"ROC: {derived.get('returnOnCost', 0)}% | "
        f"ROE: {derived.get('returnOnEquity', 0)}% | "
        f"Equity Multiple: {derived.get('equityMultiple', 0)}x | "
        f"Unlevered IRR: {derived.get('unleveredIRR', 'N/A')}% | "
        f"Levered IRR: {derived.get('leveredIRR', 'N/A')}% | "
        f"NPV (unlevered): {derived.get('npvUnlevered', 'N/A')} AED | "
        f"NPV (levered): {derived.get('npvLevered', 'N/A')} AED | "
        f"Payback quarter: {derived.get('cashBreakevenQuarter', 'N/A')}\n"
    )

    deps = FeasibilityDeps(
        price_keys=price_keys,
        context_prompt=context_prompt,
        current_plot_number=current_plot_number,
        current_area=area,
    )

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
            user_message,
            message_history=history,
            deps=deps,
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
                            payload = await _fetch_research_payload(
                                part.tool_name, part.args_as_dict()
                            )
                            if payload is not None:
                                yield f"data: {json.dumps({'type': 'show_research', 'tab': tab, 'data': payload}, default=str)}\n\n"

            new_msgs = run.new_messages_json().decode()
            yield f"data: {json.dumps({'type': 'done', 'new_messages_json': new_msgs})}\n\n"

    except Exception as e:
        logger.exception("Error in feasibility chat stream")
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
