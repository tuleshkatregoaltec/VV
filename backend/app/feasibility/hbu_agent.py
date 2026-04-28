import asyncio
import json
import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from app.config import settings
from app.feasibility.engine import compute_feasibility_summary, compute_feasibility_workbook
from app.feasibility.models import (
    FeasibilityAssumptions,
    FeasibilityPaymentPlan,
    PlotDetails,
    PlotResearch,
    Usage,
)
from app.feasibility.queries import (
    build_off_plan_pricing_confidence,
    build_off_plan_unit_benchmarks,
    get_land_sale_evidence,
    get_market_pricing,
    get_off_plan_pricing_curve,
    rank_plot_comparables,
)
from app.feasibility.queries import get_plot_details as fetch_plot_details

logger = logging.getLogger(__name__)


def _parse_max_storeys(max_height: str | None) -> int | None:
    if not max_height or "UNLIMITED" in max_height.upper():
        return None
    matches = re.findall(r"\d+", max_height)
    if not matches:
        return None
    storeys = int(matches[-1])
    return storeys if storeys > 0 else None


def _parse_max_coverage(max_coverage: str | None) -> float | None:
    if not max_coverage:
        return None
    digits = "".join(ch for ch in max_coverage if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def build_assumptions_scaffold(plot: PlotDetails, usage: Usage) -> FeasibilityAssumptions:
    inferred_far = (
        plot.far
        if plot.far and plot.far > 0
        else (
            plot.max_gfa_sqm / plot.plot_area_sqm
            if plot.plot_area_sqm > 0 and plot.max_gfa_sqm > 0
            else 0
        )
    )
    tower_count = (
        3
        if plot.plot_area_sqm >= 16000 or plot.max_gfa_sqm >= 50000
        else 2
        if plot.plot_area_sqm >= 8000 or plot.max_gfa_sqm >= 25000
        else 1
    )
    default_construction_cost = (
        5200 if usage == "commercial" else 4700 if usage == "mixed_use" else 4200
    )
    return FeasibilityAssumptions(
        usage=usage,
        plotAreaSqm=plot.plot_area_sqm,
        maxGfaSqm=plot.max_gfa_sqm,
        maxCoveragePct=_parse_max_coverage(plot.max_coverage),
        maxStoreys=_parse_max_storeys(plot.max_height),
        maxFar=round(inferred_far, 4),
        numberOfTowers=tower_count,
        numberOfFloors=_parse_max_storeys(plot.max_height) or 20,
        buaMultiplier=1.3,
        nsaEfficiencyPct=80,
        landPricePsqm=0,
        constructionCostPsqmBua=default_construction_cost,
        designSupervisionPct=7 if usage == "commercial" else 6.5 if usage == "mixed_use" else 6,
        salesAgentFeePct=5,
        marketingCostPct=1,
        contingencyPct=5,
        financeRatePct=9,
        arrangementFeePct=1,
        commitmentFeePct=0.5,
        debtToCostRatio=0.55,
        presaleThresholdPct=35,
        escrowRetentionPct=5,
        standardParkingRatio=1,
        largeUnitThresholdSqm=150,
        largeUnitParkingRatio=2,
        demolitionEnabled=False,
        salesCommencementDate="2026-06-01",
        salesPeriodMonths=18,
        demolitionEnablingDate="2026-04-01",
        constructionDate="2026-07-01",
        handoverDate="2029-01-01",
        landAcquisitionCostOverrideAed=None,
        designSupervisionCostOverrideAed=None,
        constructionCostOverrideAed=None,
        demolitionCostAed=0,
        infrastructureCostAed=8_000_000,
        governmentFeesAed=5_000_000,
        marketingCostOverrideAed=None,
        salesAgentFeesOverrideAed=None,
        masterCommunityFeesAed=3_500_000,
        ffeOsePreopeningCostAed=0,
        contingencyCostOverrideAed=None,
        midPointInflationPct=4,
        vatPct=5,
        debtFundingAed=0,
        equityFundingAed=0,
        brokerageFeeAed=0,
        legalDdCostAed=0,
        landAcquisitionDate="2026-03-17",
        landLoanLtvPct=65,
        eiborRatePct=4.85,
        landLoanSpreadBps=365,
        constructionLoanSpreadBps=465,
        preHandoverMilestoneDate="2028-07-01",
        debtRepaymentMode="bullet_at_handover",
        unitConfigs=[],
        paymentPlan=FeasibilityPaymentPlan(depositPct=20, constructionPct=40, handoverPct=40),
    )


def _plot_context(plot: PlotDetails) -> str:
    """Render a compact, agent-readable summary of the plot plot data."""
    land_use = (
        "\n".join(f"  {item.type}: {item.use}" for item in plot.land_use)
        if plot.land_use
        else "  (none)"
    )
    notes = "\n".join(f"  - {n}" for n in plot.general_notes) if plot.general_notes else "  (none)"
    setbacks = (
        ", ".join(f"{k}: {v}" for k, v in plot.setbacks.items())
        if plot.setbacks
        else "not specified"
    )
    warnings = "\n".join(f"  ! {w}" for w in plot.warnings) if plot.warnings else "  (none)"
    return (
        f"Plot number:      {plot.plot_number}\n"
        f"Community:        {plot.community_name}\n"
        f"Project name:     {plot.project_name or '—'}\n"
        f"Master developer: {plot.master_developer or '—'}\n"
        f"Plot area:        {plot.plot_area_sqm:,.1f} sqm\n"
        f"Max GFA:          {plot.max_gfa_sqm:,.1f} sqm\n"
        f"Max height:       {plot.max_height or 'not specified'}\n"
        f"Max coverage:     {plot.max_coverage or 'not specified'}\n"
        f"GFA type:         {plot.gfa_type or '—'}\n"
        f"FAR:              {plot.far or 'derived'}\n"
        f"Inferred usage:   {plot.inferred_usage}\n"
        f"Site plan:        issued {plot.site_plan_issue_date or '?'}, expires {plot.site_plan_expiry_date or '?'}\n"
        f"Verified:         {plot.is_verified}{' — ' + plot.verify_comments if plot.verify_comments else ''}\n"
        f"Setbacks:         {setbacks}\n"
        f"Land use:\n{land_use}\n"
        f"General notes:\n{notes}\n"
        f"GIS warnings:\n{warnings}"
    )


@dataclass
class HBUSeedDeps:
    plot_number: str
    plot_details: PlotDetails
    scaffold: FeasibilityAssumptions
    usage_override: Usage | None = None


class HBUSeedDraft(BaseModel):
    headline: str
    summary: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: FeasibilityAssumptions


model = OpenAIChatModel(
    model_name=settings.DEFAULT_CHAT_MODEL,
    provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
)

_SYSTEM_PROMPT = """\
You are a Dubai real estate development advisor producing an initial highest-and-best-use (HBU) \
feasibility study for a specific GIS plot. Your output seeds a developer's financial workbook.

The plot data and a default assumption scaffold are included in the user message. \
Use them as your starting point — you do not need tools to retrieve them.

━━━ PHASE 1 — RESEARCH ━━━
Call all five research tools in a single parallel batch:
  • get_existing_market_pricing   — secondary-market median prices by unit type (pricing floor)
  • get_off_plan_market_pricing   — off-plan prices segmented by handover horizon bucket (primary)
  • get_pricing_comparables       — completed/selling projects ranked by similarity to this plot
  • get_pipeline_comparables      — planned/under-construction projects in the same area (supply risk)
  • get_plot_land_sales           — recent land transactions near this plot size (land cost anchor)

━━━ PHASE 2 — PROJECT CONCEPT & UNIT MIX ━━━
Before touching any cost or funding input, lock in the revenue side of the model.

  1. Project tier: classify the plot as standard / premium / ultra-premium based on location,
     the pricing comp set, and achievable selling rates. This determines product quality and
     acceptable cost levels.

  2. Unit mix: design a mix that maximises gross saleable area (GSA) within the zoning cap.
     Target GSA ≈ maxGfaSqm × nsaEfficiencyPct. Treat leaving GFA on the table as an
     opportunity cost that must be justified. Apply these rules:
       - Favour unit types with strong off-plan demand and thin pipeline saturation.
       - Avoid unit types that dominate the current pipeline (supply risk).
       - Match typical unit sizes to what the area's comparable projects deliver.
       - Use integer unit counts; ensure total NSA ≈ target GSA.

  3. Selling rates: select the off-plan horizon bucket closest to your projected handover date.
     Apply a 5–10% haircut to those benchmarks to reflect launch uncertainty. Never exceed the
     top-of-range comparable without a specific justification. Existing stock prices are a floor —
     off-plan benchmarks are primary.

  4. Timeline: set realistic dates for construction start, handover, and sales commencement.
     Flag renewal risk if handover is within 12 months of site plan expiry.

━━━ PHASE 3 — COSTS ━━━
With the unit mix and revenue locked, size the cost stack.

  1. Land cost (landPricePsqm): anchor strictly to the land sales data.
       - Discard any transaction where price_sqm is 0 or price_aed < 500,000 (government
         transfers and nominal conveyances — not arm's-length market evidence).
       - From the remaining arm's-length transactions, use the most recent comparable as the
         primary reference. Apply a recency premium only if price trends in the data justify it.
       - If the only valid transactions are older than 24 months, flag land cost as a critical
         warning and note the staleness.
       - If no valid arm's-length transactions exist at all, set landPricePsqm = 0 and raise a
         hard warning — do not invent a number.

  2. Construction cost (constructionCostPsqmBua): scale to tower height and product tier.
       - Standard residential (≤20 floors): AED 3,500–4,500/sqm BUA
       - Mid-rise (21–40 floors): AED 4,000–5,000/sqm BUA
       - High-rise (41–60 floors): AED 4,800–5,500/sqm BUA
       - Super-tall (61+ floors): AED 5,500–7,000/sqm BUA
     Add 10–15% for premium/ultra-premium product tier.

  3. Other costs: keep infrastructure, government fees, and master community fees at the scaffold
     defaults unless you have a specific reason to deviate. Flag deviations.

━━━ PHASE 4 — VERIFY & FINANCE ━━━
Call compute_workbook with debtFundingAed = 0 and equityFundingAed = 0 first to read the
unlevered cash position, then size financing to cover only the timing gap.

  After each compute_workbook call:
    • Check modeled_gfa_sqm ≤ maxGfaSqm. If over the cap, reduce unit count or sizes.
    • Read peak_debt_aed: set debtFundingAed = round up to the nearest AED 10M. This is the
      minimum debt facility needed to avoid an overdraw during construction.
    • Read funding_gap_aed (= total_costs − total_sources):
        - Negative gap means sources exceed uses (surplus) — acceptable.
        - Positive gap means a shortfall — hard failure. Increase equityFundingAed to close it.
      If gap > 0: set equityFundingAed += round_up(gap × 1.05, 10M) to close the deficit with a
      small buffer. If gap ≤ 0, leave equityFundingAed at 0 unless IRR calculations require it.
    • Call compute_workbook again with the sized facilities. The funding_gap should now be ≤ 0
      (a small surplus is fine). If a hard funding gap remains, iterate once more.
    • If returns or margin look wrong after financing, revisit the assumptions driving the issue
      and call compute_workbook again. Iterate as many times as needed.
    • Leave any unresolved validation warnings in the output warnings list.

━━━ OUTPUT ━━━
  headline:    one-line project description
  summary:     6–10 bullets — site, programme, pricing rationale, cost, return headline, key risks
  constraints: hard zoning/regulatory facts from the plot data
  warnings:    specific and actionable (not generic boilerplate)
  assumptions: final FeasibilityAssumptions

A loss-making result is acceptable to output — flag it clearly and name the sensitivity lever.
Never invent data. If evidence is absent, say so.
Zoning and GFA constraints from the plot data are absolute.\
"""


hbu_seed_agent = Agent(
    model,
    deps_type=HBUSeedDeps,
    output_type=HBUSeedDraft,
    model_settings={"temperature": 0.1},
    system_prompt=_SYSTEM_PROMPT,
)


@hbu_seed_agent.tool
async def get_existing_market_pricing(
    ctx: RunContext[HBUSeedDeps], usage: Usage | None = None
) -> list[dict]:
    """Secondary-market (existing stock) median transaction prices by unit type for this plot's area.

    Returns: list of {unit_type, transaction_count, median_price_sqm, avg_area_sqm}.
    Use as a pricing floor — existing stock typically trades below off-plan launch prices.
    Returns an empty list if no data is available for this area.
    """
    rows = await get_market_pricing(
        ctx.deps.plot_details.community_name,
        usage or ctx.deps.usage_override or ctx.deps.plot_details.inferred_usage,
        stage="existing",
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_off_plan_market_pricing(
    ctx: RunContext[HBUSeedDeps], usage: Usage | None = None
) -> list[dict]:
    """Off-plan transaction prices segmented by unit type and months-to-handover horizon bucket.

    Returns: list of {unit_type, horizon_bucket, avg_months_to_completion, transaction_count,
    median_price_sqm, avg_area_sqm, last_transaction_date}.
    Select the bucket whose avg_months_to_completion is closest to your projected handover horizon.
    This is the primary source for selling rate assumptions.
    Returns an empty list if no off-plan data is available for this area.
    """
    rows = await get_off_plan_pricing_curve(
        ctx.deps.plot_details.community_name,
        usage or ctx.deps.usage_override or ctx.deps.plot_details.inferred_usage,
        ctx.deps.plot_details.site_plan_expiry_date,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_pricing_comparables(
    ctx: RunContext[HBUSeedDeps], usage: Usage | None = None, limit: int = 6
) -> list[dict]:
    """Completed and actively selling projects ranked by similarity to this plot.

    Similarity scoring considers plot size, area, and usage. Returns project name, status,
    similarity score, median_price_sqm, dominant unit type, and total units.
    Use to cross-check selling rates and calibrate unit mix.
    """
    rows = await rank_plot_comparables(
        ctx.deps.plot_details,
        usage or ctx.deps.usage_override or ctx.deps.plot_details.inferred_usage,
        "pricing",
        limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_pipeline_comparables(
    ctx: RunContext[HBUSeedDeps], usage: Usage | None = None, limit: int = 6
) -> list[dict]:
    """Planned and under-construction projects in the same market area.

    Returns project name, status, similarity score, total units, and land area.
    Use to gauge supply risk and identify unit type saturation in the pipeline.
    """
    rows = await rank_plot_comparables(
        ctx.deps.plot_details,
        usage or ctx.deps.usage_override or ctx.deps.plot_details.inferred_usage,
        "pipeline",
        limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_plot_land_sales(
    ctx: RunContext[HBUSeedDeps], days: int = 1825, limit: int = 12
) -> list[dict]:
    """Recent land sale transactions for plots of similar size in this area.

    Returns: list of {instance_date, area_name, plot_area_sqm, price_aed, price_sqm, project_name}.
    Use price_sqm to anchor landPricePsqm. Consider the p25–p75 range as the credible window.
    An empty list means no land sales data is available — flag landPricePsqm as a critical warning.
    """
    rows = await get_land_sale_evidence(
        area_name=ctx.deps.plot_details.community_name,
        plot_area_sqm=ctx.deps.plot_details.plot_area_sqm,
        days=days,
        limit=limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def compute_workbook(
    ctx: RunContext[HBUSeedDeps], assumptions: FeasibilityAssumptions
) -> dict:
    """Run the financial model against the provided assumptions and return a summary.

    Returns: {success, summary} where summary contains:
      gross_revenue_aed, total_costs_incl_vat_aed, gross_profit_aed, gross_margin_pct,
      off_plan_proceeds_aed, project_irr_pct, equity_irr_pct, modeled_gfa_sqm, total_units,
      peak_debt_aed, funding_gap_aed, and a validation object.

    Key fields for financing:
      peak_debt_aed     — maximum debt drawn at any single point in time. Set debtFundingAed
                          to at least this value (rounded up) or the loan will overdraw.
      funding_gap_aed   — (total_costs_incl_vat) minus (off_plan_proceeds + debt + equity +
                          vat_refunds). Negative = surplus (OK). Positive = hard deficit.
      off_plan_proceeds_aed — total presale cash collected over the sales period. This is the
                          primary funding source; size debt and equity around what it doesn't cover.
    """
    workbook = compute_feasibility_workbook(ctx.deps.plot_details, assumptions, study=None)
    summary = compute_feasibility_summary(workbook)
    return {
        "success": True,
        "summary": summary.model_dump(mode="json"),
    }


async def generate_hbu_study(
    plot_number: str, usage_override: Usage | None = None
) -> PlotResearch | None:
    details = await fetch_plot_details(plot_number)
    if details is None:
        return None

    usage = usage_override or details.inferred_usage

    # Pre-fetch all market data in parallel — needed for PlotResearch assembly regardless of agent.
    (
        market_pricing,
        off_plan_market_pricing,
        pricing_evidence,
        competition_evidence,
        land_sales_evidence,
    ) = await asyncio.gather(
        get_market_pricing(details.community_name, usage, stage="existing"),
        get_off_plan_pricing_curve(details.community_name, usage, details.site_plan_expiry_date),
        rank_plot_comparables(details, usage, "pricing"),
        rank_plot_comparables(details, usage, "pipeline"),
        get_land_sale_evidence(
            area_name=details.community_name,
            plot_area_sqm=details.plot_area_sqm,
            days=1825,
            limit=12,
        ),
    )

    from datetime import date

    target_horizon_months = (
        max(1, round((date.fromisoformat(details.site_plan_expiry_date) - date.today()).days / 30))
        if details.site_plan_expiry_date
        else 36
    )
    fallback_prices = {row.unit_type: row.median_price_sqm for row in market_pricing}
    off_plan_benchmarks = build_off_plan_unit_benchmarks(
        off_plan_market_pricing, target_horizon_months, fallback_prices
    )
    off_plan_confidence = build_off_plan_pricing_confidence(
        off_plan_market_pricing, target_horizon_months
    )

    scaffold = build_assumptions_scaffold(details, usage)

    benchmark_lines = (
        "\n".join(
            f"  {b.unit_type}: AED {b.selected_price_sqm:.0f}/sqm "
            f"({b.confidence_label} confidence, {b.transaction_count} txns, {b.selected_horizon_bucket})"
            for b in off_plan_benchmarks
        )
        or "  No off-plan benchmarks available — use existing market pricing."
    )

    prompt = (
        f"=== PLOT DOSSIER ===\n"
        f"{_plot_context(details)}\n\n"
        f"=== OFF-PLAN PRICING BENCHMARKS (horizon-adjusted to {target_horizon_months}m) ===\n"
        f"{benchmark_lines}\n\n"
        f"=== DEFAULT ASSUMPTION SCAFFOLD ===\n"
        f"Computed from the plot's GFA, height, and inferred usage. "
        f"Override any value where evidence supports a better estimate. "
        f"Unit configs and funding amounts must be set by you.\n"
        f"{json.dumps(scaffold.model_dump(mode='json'), indent=2)}\n\n"
        f"Research the market, form your assumptions, verify with compute_workbook, "
        f"and return the HBU study for plot {plot_number} (usage: {usage})."
    )

    result = await hbu_seed_agent.run(
        prompt,
        deps=HBUSeedDeps(
            plot_number=plot_number,
            plot_details=details,
            scaffold=scaffold,
            usage_override=usage_override,
        ),
        usage_limits=UsageLimits(request_limit=15),
    )
    draft = result.output

    warnings = list(details.warnings)
    warnings.extend(item for item in draft.warnings if item not in warnings)
    if not market_pricing:
        warnings.append("No segmented existing transaction pricing was found for this plot area.")
    if not off_plan_market_pricing:
        warnings.append("No off-plan pricing curve was found for this plot area.")

    land_rates = sorted(row.price_sqm for row in land_sales_evidence)
    land_cost_low = land_cost_mid = land_cost_high = None
    if land_rates and details.plot_area_sqm > 0:
        land_cost_low = round(
            land_rates[max(0, int((len(land_rates) - 1) * 0.25))] * details.plot_area_sqm, 2
        )
        land_cost_mid = round(land_rates[len(land_rates) // 2] * details.plot_area_sqm, 2)
        land_cost_high = round(
            land_rates[min(len(land_rates) - 1, int((len(land_rates) - 1) * 0.75))]
            * details.plot_area_sqm,
            2,
        )

    return PlotResearch(
        plot_number=details.plot_number,
        usage=usage,
        market_area=details.community_name,
        headline=draft.headline,
        summary=draft.summary,
        constraints=draft.constraints,
        pricing_evidence=pricing_evidence,
        competition_evidence=competition_evidence,
        land_sales_evidence=land_sales_evidence,
        market_pricing=market_pricing,
        off_plan_market_pricing=off_plan_market_pricing,
        off_plan_pricing_confidence=off_plan_confidence,
        off_plan_unit_benchmarks=off_plan_benchmarks,
        assumptions=draft.assumptions,
        warnings=warnings,
        land_cost_estimate_aed_low=land_cost_low,
        land_cost_estimate_aed_mid=land_cost_mid,
        land_cost_estimate_aed_high=land_cost_high,
    )
