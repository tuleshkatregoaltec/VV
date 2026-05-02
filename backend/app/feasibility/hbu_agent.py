import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.usage import UsageLimits

from app.area.service import get_area_detail
from app.config import settings
from app.feasibility.models import (
    BtrUnitConfig,
    DevelopmentModel,
    FeasibilityAssumptions,
    FeasibilityPaymentPlan,
    PlotDetails,
    PlotResearch,
    RentalComparableProject,
    RentalMarketSummary,
    RentalRateBySizeBand,
    Usage,
)
from app.feasibility.queries import (
    build_off_plan_pricing_confidence,
    build_off_plan_unit_benchmarks,
    get_land_sale_evidence,
    get_market_pricing,
    get_off_plan_pricing_curve,
    get_rental_rates_by_size_band,
    rank_plot_comparables,
    resolve_market_area,
)
from app.feasibility.queries import get_plot_details as fetch_plot_details
from app.feasibility.workbook import compute_feasibility_summary, compute_feasibility_workbook
from app.project.service import get_project_market_snapshot

logger = logging.getLogger(__name__)


def _parse_max_storeys(max_height: str | None) -> int | None:
    if not max_height:
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


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    idx = min(len(values) - 1, max(0, round((len(values) - 1) * pct)))
    return values[idx]


def _land_price_band_psqm(
    land_sales_evidence: list,
) -> tuple[float | None, float | None, float | None]:
    prices = sorted(
        row.price_sqm for row in land_sales_evidence if row.price_sqm and row.price_sqm > 0
    )
    if not prices:
        return None, None, None
    return (
        _percentile(prices, 0.25),
        _percentile(prices, 0.5),
        _percentile(prices, 0.75),
    )


def _land_anchor_summary(
    land_sales_evidence: list,
    plot_area_sqm: float,
    area_name: str = "",
) -> str:
    p25, p50, p75 = _land_price_band_psqm(land_sales_evidence)
    if p25 is None or p50 is None or p75 is None:
        return "No comparable land-sale anchor was found. Use the per-GFA-sqm Dubai market reference in the prompt."

    lines = [
        f"Land-sale anchor (AED/plot sqm): p25={p25:,.0f}  median={p50:,.0f}  p75={p75:,.0f}",
        f"Implied total land cost:         p25=AED {p25 * plot_area_sqm:,.0f}  "
        f"median=AED {p50 * plot_area_sqm:,.0f}  p75=AED {p75 * plot_area_sqm:,.0f}",
    ]
    low_sqft, base_sqft, high_sqft = _gfa_rate_band_sqft(area_name)
    lines.append(
        f"Dubai market sanity band ({area_name or 'default'}): AED {low_sqft:,.0f}-{high_sqft:,.0f}/sqft GFA "
        f"(base case ~AED {base_sqft:,.0f}/sqft GFA). Clip obvious outliers to this range."
    )

    # GFA-normalised rates (if available)
    gfa_prices = sorted(
        row.price_per_gfa_sqm
        for row in land_sales_evidence
        if row.price_per_gfa_sqm and row.price_per_gfa_sqm > 0
    )
    if gfa_prices:
        g25 = _percentile(gfa_prices, 0.25)
        g50 = _percentile(gfa_prices, 0.5)
        g75 = _percentile(gfa_prices, 0.75)
        # Convert sqm to sqft for the prompt (Dubai convention)
        SQM_TO_SQFT = 10.764
        lines.append(
            f"FAR-normalised (AED/GFA sqm):    p25={g25:,.0f}  median={g50:,.0f}  p75={g75:,.0f}  "
            f"[AED/sqft: p25={g25 / SQM_TO_SQFT:,.0f}  median={g50 / SQM_TO_SQFT:,.0f}  p75={g75 / SQM_TO_SQFT:,.0f}]"
        )
        lines.append("Cross-check this GFA rate against the Dubai market sanity band above.")
    else:
        lines.append(
            "No GFA-normalised rate available (FAR unknown for comparables). Apply the Dubai per-sqft-GFA reference as the primary cross-check."
        )

    return "\n".join(lines)


def _effective_land_price_psqm(assumptions: FeasibilityAssumptions, plot_area_sqm: float) -> float:
    if assumptions.landAcquisitionCostOverrideAed and plot_area_sqm > 0:
        return assumptions.landAcquisitionCostOverrideAed / plot_area_sqm
    return assumptions.landPricePsqm


# Dubai per-sqft-GFA market reference bands, used as sanity bounds rather than hard floors.
_DUBAI_GFA_RATE_BANDS: list[tuple[list[str], tuple[float, float, float]]] = [
    (["downtown", "difc", "palm jumeirah", "palm"], (500.0, 700.0, 900.0)),
    (
        ["business bay", "jumeirah lake towers", "jlt", "jbr", "marina", "dubai marina"],
        (300.0, 400.0, 500.0),
    ),
    (["dubai hills", "city walk", "bluewaters"], (250.0, 325.0, 400.0)),
    (["jumeirah", "umm suqeim", "al barsha"], (200.0, 275.0, 350.0)),
    (
        [
            "jumeirah village circle",
            "jvc",
            "jumeirah village triangle",
            "jvt",
            "dubai silicon oasis",
            "dso",
        ],
        (100.0, 150.0, 200.0),
    ),
    (["meydan", "mbr city", "mohammed bin rashid", "dubai south"], (120.0, 185.0, 250.0)),
]
_DEFAULT_GFA_RATE_BAND_SQFT = (120.0, 180.0, 250.0)


def _gfa_rate_band_sqft(area_name: str) -> tuple[float, float, float]:
    area_lower = (area_name or "").lower()
    for keywords, band in _DUBAI_GFA_RATE_BANDS:
        if any(kw in area_lower for kw in keywords):
            return band
    return _DEFAULT_GFA_RATE_BAND_SQFT


def _gfa_sqft_to_plot_psqm(rate_sqft_gfa: float, far: float) -> float:
    sqft_to_sqm = 10.764
    return rate_sqft_gfa * sqft_to_sqm * far


def _land_price_anchor_psqm(
    land_sales_evidence: list,
    area_name: str = "",
    far: float = 0.0,
) -> float | None:
    """Return a bounded land anchor in AED/plot sqm.

    DLD plot-sqm medians can be badly distorted when the comparable has different FAR or a
    commercial/mixed-use residual. For BTR seeding, prefer FAR-normalized evidence and clip it
    to a broad Dubai AED/sqft-GFA market band.
    """
    p25, p50, _ = _land_price_band_psqm(land_sales_evidence)
    if far <= 0:
        return p50

    low_sqft, base_sqft, high_sqft = _gfa_rate_band_sqft(area_name)
    low_psqm = _gfa_sqft_to_plot_psqm(low_sqft, far)
    base_psqm = _gfa_sqft_to_plot_psqm(base_sqft, far)
    high_psqm = _gfa_sqft_to_plot_psqm(high_sqft, far)

    gfa_prices = sorted(
        row.price_per_gfa_sqm
        for row in land_sales_evidence
        if row.price_per_gfa_sqm and row.price_per_gfa_sqm > 0
    )
    gfa_median_psqm_plot = None
    if gfa_prices:
        median_gfa_sqm = _percentile(gfa_prices, 0.5)
        if median_gfa_sqm:
            gfa_median_psqm_plot = median_gfa_sqm * far

    raw_anchor = gfa_median_psqm_plot or p50 or base_psqm
    if raw_anchor is None:
        return base_psqm

    # Allow evidence to sit below the market band if DLD supports it, but do not allow high-FAR
    # or commercial outliers to push the seed above the bracket high.
    floor = min(low_psqm, p25 or low_psqm)
    return round(min(max(raw_anchor, floor), high_psqm), 2)


def _gfa_rate_floor_psqm_plot(area_name: str, far: float) -> float | None:
    """Return the minimum land cost in AED/plot sqm based on Dubai GFA-rate market reference.

    Converts AED/sqft GFA → AED/sqm GFA → AED/sqm plot using FAR.
    Returns None if FAR is unknown/zero.
    """
    if not far or far <= 0:
        return None
    return _gfa_sqft_to_plot_psqm(_gfa_rate_band_sqft(area_name)[0], far)


def _gfa_rate_cap_psqm_plot(area_name: str, far: float) -> float | None:
    if not far or far <= 0:
        return None
    return _gfa_sqft_to_plot_psqm(_gfa_rate_band_sqft(area_name)[2], far)


def _enforce_land_price_floor(
    assumptions: FeasibilityAssumptions,
    land_sales_evidence: list,
    plot_area_sqm: float,
    area_name: str = "",
    far: float = 0.0,
) -> tuple[FeasibilityAssumptions, str | None]:
    p25, p50, _ = _land_price_band_psqm(land_sales_evidence)
    current_land_price = _effective_land_price_psqm(assumptions, plot_area_sqm)

    gfa_floor = _gfa_rate_floor_psqm_plot(area_name, far)
    gfa_cap = _gfa_rate_cap_psqm_plot(area_name, far)
    if plot_area_sqm <= 0:
        return assumptions, None

    floor_candidates = [f for f in [p25, gfa_floor] if f is not None]
    effective_floor = min(floor_candidates) if floor_candidates else None
    effective_cap = gfa_cap
    bounded_price = current_land_price
    reason: str | None = None

    if effective_floor is not None and bounded_price < effective_floor:
        bounded_price = p50 or effective_floor
        reason = "below the supported land evidence / market sanity range"
    if effective_cap is not None and bounded_price > effective_cap:
        bounded_price = effective_cap
        low_sqft, _, high_sqft = _gfa_rate_band_sqft(area_name)
        reason = (
            f"above the {area_name or 'Dubai'} AED/sqft-GFA sanity band "
            f"({low_sqft:,.0f}-{high_sqft:,.0f}/sqft GFA)"
        )

    if reason is None or abs(bounded_price - current_land_price) < 1:
        return assumptions, None

    bounded_price = round(bounded_price, 2)
    bounded_cost = round(plot_area_sqm * bounded_price, 2)
    warning = (
        f"Land acquisition was bounded to AED {bounded_price:,.0f}/plot sqm "
        f"(total AED {bounded_cost:,.0f}) because the generated land basis "
        f"(AED {current_land_price:,.0f}/plot sqm) was {reason}."
    )
    return (
        assumptions.model_copy(
            update={
                "landPricePsqm": bounded_price,
                "landAcquisitionCostOverrideAed": bounded_cost,
            }
        ),
        warning,
    )


def _normalize_capital_stack(
    plot: PlotDetails, assumptions: FeasibilityAssumptions
) -> tuple[FeasibilityAssumptions, str | None]:
    workbook = compute_feasibility_workbook(plot, assumptions, study=None)
    required_uses = round(workbook.costs.total_costs_incl_vat_aed, 2)
    requested_debt = max(assumptions.debtFundingAed, 0)
    if requested_debt <= 0 and assumptions.debtToCostRatio > 0:
        requested_debt = round(
            required_uses * min(max(assumptions.debtToCostRatio, 0), 1),
            2,
        )

    normalized_debt = round(min(requested_debt, required_uses), 2)
    normalized_equity = round(max(required_uses - normalized_debt, 0), 2)

    if (
        abs((assumptions.debtFundingAed or 0) - normalized_debt) < 1
        and abs((assumptions.equityFundingAed or 0) - normalized_equity) < 1
    ):
        return assumptions, None

    warning = (
        "Debt and sponsor equity were rebalanced to a non-negative capital stack so "
        "sources cover uses in the underwriting view."
    )
    return (
        assumptions.model_copy(
            update={
                "debtFundingAed": normalized_debt,
                "equityFundingAed": normalized_equity,
            }
        ),
        warning,
    )


def _annual_rent_to_monthly_rent(annual_rate_psqm: float | None, avg_size_sqm: float) -> int:
    if not annual_rate_psqm or annual_rate_psqm <= 0 or avg_size_sqm <= 0:
        return 0
    return max(0, round((annual_rate_psqm * avg_size_sqm) / 12))


def _mirror_btr_to_unit_configs(assumptions: FeasibilityAssumptions) -> FeasibilityAssumptions:
    btr_unit_configs = list(assumptions.btrUnitConfigs or [])
    if assumptions.developmentModel != "build_to_rent_residential" or not btr_unit_configs:
        return assumptions

    unit_configs = [
        {
            "id": cfg.id or f"btr-{idx + 1}",
            "label": cfg.label or f"Rental {idx + 1}",
            "units": cfg.units,
            "avgSizeSqm": cfg.avgSizeSqm,
            "sellingRatePsqm": 0.0,
            "typicalFloor": 0,
            "parkingRatio": cfg.parkingRatio,
        }
        for idx, cfg in enumerate(btr_unit_configs)
    ]
    return assumptions.model_copy(
        update={
            "unitConfigs": unit_configs,
            "marketingCostPct": 0,
            "salesAgentFeePct": 0,
            "marketingCostOverrideAed": 0,
            "salesAgentFeesOverrideAed": 0,
        }
    )


def _band_rate_for_size(
    size_sqm: float,
    size_band_rates: list[RentalRateBySizeBand],
    fallback_psm_annual: float | None,
) -> float | None:
    """Return the per-band median AED/sqm/yr for a given unit size, falling back to area blended rate."""
    if size_sqm <= 0:
        return fallback_psm_annual
    for band in size_band_rates:
        lo, hi = {
            "studio": (0, 55),
            "1br": (55, 90),
            "2br": (90, 140),
            "3br": (140, 200),
            "4br+": (200, 99999),
        }.get(band.unit_type_proxy, (0, 0))
        if lo < size_sqm <= hi or (band.unit_type_proxy == "studio" and size_sqm <= 55):
            return band.median_rent_psm_annual
    return fallback_psm_annual


def _ensure_btr_assumptions(
    assumptions: FeasibilityAssumptions,
    rental_market_summary: RentalMarketSummary | None,
    size_band_rates: list[RentalRateBySizeBand] | None = None,
) -> FeasibilityAssumptions:
    blended_psm_annual = (
        rental_market_summary.avg_rent_price_sqm_12m
        if rental_market_summary and rental_market_summary.avg_rent_price_sqm_12m
        else None
    )
    bands = size_band_rates or []
    btr_unit_configs: list[BtrUnitConfig] = list(assumptions.btrUnitConfigs or [])
    # Discard agent-provided configs that are all-placeholder (units=0 or avgSizeSqm=0 on every row)
    all_invalid = bool(btr_unit_configs) and all(
        cfg.units == 0 or cfg.avgSizeSqm == 0 for cfg in btr_unit_configs
    )
    if all_invalid:
        btr_unit_configs = []
    if not btr_unit_configs and assumptions.unitConfigs:
        btr_unit_configs = [
            BtrUnitConfig(
                id=row.id,
                label=row.label,
                units=row.units,
                avgSizeSqm=row.avgSizeSqm,
                monthlyRentAed=_annual_rent_to_monthly_rent(
                    _band_rate_for_size(row.avgSizeSqm, bands, blended_psm_annual), row.avgSizeSqm
                ),
                parkingRatio=row.parkingRatio,
            )
            for row in assumptions.unitConfigs
        ]

    def _canonical_label(raw_label: str, avg_size_sqm: float, idx: int) -> str:
        """Normalise generic agent labels to proper unit type names."""
        label = (raw_label or "").strip()
        # If the agent used a generic name, derive from size
        generic_patterns = {"rental", "unit", "type", "config"}
        if not label or any(p in label.lower() for p in generic_patterns):
            if avg_size_sqm <= 0:
                return f"Unit {idx + 1}"
            if avg_size_sqm <= 55:
                return "Studio"
            if avg_size_sqm <= 90:
                return "1BR"
            if avg_size_sqm <= 140:
                return "2BR"
            if avg_size_sqm <= 200:
                return "3BR"
            return "4BR+"
        return label

    seeded_configs: list[BtrUnitConfig] = []
    for idx, cfg in enumerate(btr_unit_configs):
        avg_size_sqm = cfg.avgSizeSqm
        monthly_rent = cfg.monthlyRentAed
        seeded_configs.append(
            BtrUnitConfig(
                id=cfg.id or f"btr-{idx + 1}",
                label=_canonical_label(cfg.label, avg_size_sqm, idx),
                units=cfg.units,
                avgSizeSqm=avg_size_sqm,
                monthlyRentAed=monthly_rent
                if monthly_rent > 0
                else _annual_rent_to_monthly_rent(
                    _band_rate_for_size(avg_size_sqm, bands, blended_psm_annual), avg_size_sqm
                ),
                parkingRatio=cfg.parkingRatio,
            )
        )

    updated = assumptions.model_copy(
        update={
            "developmentModel": "build_to_rent_residential",
            "btrUnitConfigs": seeded_configs,
            "marketingCostPct": 0,
            "salesAgentFeePct": 0,
            "marketingCostOverrideAed": 0,
            "salesAgentFeesOverrideAed": 0,
            "btrHoldPeriodYears": assumptions.btrHoldPeriodYears or 10,
            "btrLeaseUpPaceUnitsPerMonth": assumptions.btrLeaseUpPaceUnitsPerMonth or 20,
            "btrStabilizedOccupancyPct": assumptions.btrStabilizedOccupancyPct or 95,
            "btrFreeRentMonths": assumptions.btrFreeRentMonths or 2,
            "btrAnnualRentGrowthPct": assumptions.btrAnnualRentGrowthPct or 3,
            "btrMarketRentGrowthPct": assumptions.btrMarketRentGrowthPct
            or assumptions.btrAnnualRentGrowthPct
            or 3,
            "btrRenewalRentGrowthPct": assumptions.btrRenewalRentGrowthPct
            or assumptions.btrAnnualRentGrowthPct
            or 3,
            "btrGeneralVacancyPct": assumptions.btrGeneralVacancyPct or 5,
            "btrPropertyManagementPct": assumptions.btrPropertyManagementPct or 5,
            "btrRepairsMaintenancePsqm": assumptions.btrRepairsMaintenancePsqm or 50,
            "btrInsurancePsqm": assumptions.btrInsurancePsqm or 10,
            "btrServiceChargePsqm": assumptions.btrServiceChargePsqm or 80,
            "btrUtilitiesPsqm": assumptions.btrUtilitiesPsqm or 30,
            "btrMarketingLeasingPct": assumptions.btrMarketingLeasingPct or 2,
            "btrCapexReservePct": assumptions.btrCapexReservePct or 5,
            "btrParkingIncomeAed": assumptions.btrParkingIncomeAed or 0,
            "btrAncillaryIncomeAed": assumptions.btrAncillaryIncomeAed or 0,
            "btrAncillaryGrowthPct": assumptions.btrAncillaryGrowthPct or 3,
            "btrStabilizedFreeRentMonths": assumptions.btrStabilizedFreeRentMonths or 2,
            "btrOpExGrowthPct": assumptions.btrOpExGrowthPct or 3,
            "btrDevCostEscalationPct": assumptions.btrDevCostEscalationPct
            or assumptions.midPointInflationPct
            or 4,
            "btrTerminalGrowthPct": assumptions.btrTerminalGrowthPct
            or assumptions.btrAnnualRentGrowthPct
            or 3,
            "btrCreditLossPct": assumptions.btrCreditLossPct or 1,
            "btrPayrollPsqm": assumptions.btrPayrollPsqm or 40,
            "btrGeneralAdminPct": assumptions.btrGeneralAdminPct or 1,
            "btrContractServicesPsqm": assumptions.btrContractServicesPsqm or 25,
            "btrModelUnits": assumptions.btrModelUnits or 1,
            "btrExitCapRatePct": assumptions.btrExitCapRatePct or 7,
            "btrExitCostPct": assumptions.btrExitCostPct or 6,
            "btrPermDebtLtvPct": assumptions.btrPermDebtLtvPct or 65,
            "btrPermDebtRatePct": assumptions.btrPermDebtRatePct or 6,
            "btrPermDebtSpreadBps": assumptions.btrPermDebtSpreadBps or 165,
            "btrPermDebtAmortYears": assumptions.btrPermDebtAmortYears or 25,
            "btrPermDebtPointsPct": assumptions.btrPermDebtPointsPct or 1,
            "btrPermDebtIoYears": assumptions.btrPermDebtIoYears or 1,
            "btrDscrMinimum": assumptions.btrDscrMinimum or 1.25,
            "btrRefiCapRatePct": assumptions.btrRefiCapRatePct or 7,
        }
    )
    return _mirror_btr_to_unit_configs(updated)


def _ensure_bts_assumptions(assumptions: FeasibilityAssumptions) -> FeasibilityAssumptions:
    return assumptions.model_copy(update={"developmentModel": "build_to_sell_residential"})


def build_assumptions_scaffold(
    plot: PlotDetails,
    usage: Usage,
    land_price_anchor_psqm: float | None = None,
    development_model: DevelopmentModel = "build_to_sell_residential",
) -> FeasibilityAssumptions:
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
        maxCoveragePct=_parse_max_coverage(plot.max_coverage) or 0.0,
        maxStoreys=_parse_max_storeys(plot.max_height) or 0,
        maxFar=round(inferred_far, 4),
        numberOfTowers=tower_count,
        numberOfFloors=_parse_max_storeys(plot.max_height) or 20,
        buaMultiplier=1.3,
        nsaEfficiencyPct=80,
        landPricePsqm=round(land_price_anchor_psqm or 0, 2),
        constructionCostPsqmBua=default_construction_cost,
        designSupervisionPct=7 if usage == "commercial" else 6.5 if usage == "mixed_use" else 6,
        salesAgentFeePct=0 if development_model == "build_to_rent_residential" else 5,
        marketingCostPct=0 if development_model == "build_to_rent_residential" else 1,
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
        landAcquisitionCostOverrideAed=0,
        designSupervisionCostOverrideAed=0,
        constructionCostOverrideAed=0,
        demolitionCostAed=0,
        infrastructureCostAed=8_000_000,
        governmentFeesAed=5_000_000,
        marketingCostOverrideAed=0,
        salesAgentFeesOverrideAed=0,
        masterCommunityFeesAed=3_500_000,
        ffeOsePreopeningCostAed=0,
        contingencyCostOverrideAed=0,
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
        developmentModel=development_model,
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
    market_area: str
    scaffold: FeasibilityAssumptions
    development_model: DevelopmentModel
    usage_override: Usage | None = None


class HBUSeedDraft(BaseModel):
    headline: str
    summary: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    assumptions: FeasibilityAssumptions


def _tool_usage(ctx: RunContext[HBUSeedDeps], usage: Usage) -> Usage:
    return (
        usage
        if usage != "unknown"
        else ctx.deps.usage_override or ctx.deps.plot_details.inferred_usage
    )


model = OpenAIChatModel(
    model_name=settings.DEFAULT_CHAT_MODEL,
    provider=OpenRouterProvider(api_key=settings.OPENROUTER_API_KEY),
)

_SYSTEM_PROMPT = """\
You are a Dubai real estate development advisor producing an initial highest-and-best-use (HBU) \
feasibility study for a specific GIS plot. Your output seeds a developer's financial workbook.

The plot plot data and a default assumption scaffold are included in the user message. \
Use them as your starting point — you do not need tools to retrieve them.

First inspect `development_model` in the user message. The underwriting path depends on it:
  • `build_to_sell_residential` means BTS and uses sales evidence.
  • `build_to_rent_residential` means BTR and uses rental evidence.
These models are separate. Never reuse BTS pricing logic for BTR.

━━━ PHASE 1 — RESEARCH ━━━
If the model is BTS, call these tools in one parallel batch:
  • get_existing_market_pricing   — secondary-market median prices by unit type (pricing floor)
  • get_off_plan_market_pricing   — off-plan prices segmented by handover horizon bucket (primary)
  • get_pricing_comparables       — completed/selling projects ranked by similarity to this plot
  • get_pipeline_comparables      — planned/under-construction projects in the same area (supply risk)
  • get_plot_land_sales           — recent land transactions near this plot size (land cost anchor)

If the model is BTR, call these tools in one parallel batch:
  • get_area_rental_market        — master-community rental averages and gross yield context
  • get_rental_comparables        — rental comps with achieved rent psqm and annual rents
  • get_pipeline_comparables      — planned/under-construction projects in the same area (supply risk)
  • get_plot_land_sales           — recent land transactions near this plot size (land cost anchor)

━━━ PHASE 2 — FORM ASSUMPTIONS ━━━
Using the research evidence, decide on the best set of assumptions for this plot. You have full \
freedom over every assumption — use the scaffold as a starting point and override anything where \
the evidence or your judgement supports a better estimate.

Key things to reason through:
  • Land cost: anchor to comparable land sales AND the per-GFA-sqm sanity check. The LAND COST ANCHOR
    section shows both AED/plot-sqm (from DLD data) and AED/GFA-sqm (normalised to this plot's FAR).
    Cross-check both: if the DLD evidence implies a per-GFA-sqm rate far below Dubai norms, weight
    towards the Dubai market reference range instead. Typical Dubai residential land cost ranges
    (AED per sqft of max GFA, as a market reality check — use the relevant bracket for this location):
      Downtown / DIFC / Palm Jumeirah: AED 500–900/sqft GFA
      Business Bay / JLT / JBR / Marina: AED 300–500/sqft GFA
      Dubai Hills / City Walk / Bluewaters: AED 250–400/sqft GFA
      Jumeirah / Umm Suqeim / Al Barsha: AED 200–350/sqft GFA
      JVC / JVT / Dubai Silicon Oasis: AED 100–200/sqft GFA
      Meydan / MBR City / Dubai South: AED 120–250/sqft GFA
    If land evidence is absent or the implied per-GFA rate is below the bracket floor, use the floor
    as your anchor and flag it as a warning. Do not set landPricePsqm below the p25 DLD evidence floor.
  • Project tier and unit mix: match the scale and product type to what the location and GFA support.
    Design the unit mix to maximise GFA utilisation and appeal to the likely buyer profile.
    Consider supply pipeline when choosing unit types to avoid saturated segments.
  • For BTS selling rates: off-plan pricing is primary; existing stock sets a floor. Apply a conservative
    haircut to reflect launch uncertainty.
  • For BTR rents: use the size-band rental rates in the market context as your primary anchor — each band
    gives you a per-sqm/yr rate matched to unit size. Convert to monthly rent per config using:
    monthlyRentAed = median_rent_psm_annual × avgSizeSqm / 12. Fall back to the blended area rate only
    if no band data exists. Do not use sales evidence, GDV, or gross sales to justify BTR pricing.
  • BTR unit mix labels: always use standard Dubai unit type names — "Studio", "1BR", "2BR", "3BR", "4BR+".
    Never use generic names like "Rental 1". Every btrUnitConfig must have a non-zero avgSizeSqm and
    a non-zero units count — configs with zero units or zero size are invalid. Match avgSizeSqm to the
    typical Dubai size for that type: Studio ~42 sqm, 1BR ~70 sqm, 2BR ~110 sqm, 3BR ~160 sqm.
  • Construction cost: scale to tower height and product complexity.
  • Timeline: be realistic about land-to-launch lead time, presale threshold, build period, and
    site plan expiry. Flag renewal risk if handover is close to expiry.
  • Funding for BTS: set debtFundingAed and equityFundingAed to whatever capital structure makes sense
    given the cost base and off-plan proceeds profile. Ensure sources cover uses.
  • Funding for BTR: think like CRE underwriting. Focus on stabilized occupancy, rental rate, NOI, exit cap,
    and permanent debt constraints. You may still set debtFundingAed and equityFundingAed, but do not use
    sale proceeds or presales as the underwriting basis.

━━━ PHASE 3 — VERIFY & ITERATE ━━━
If the model is BTS, call compute_workbook with your assumptions. Review the result:
  • Check modeled_gfa_sqm fits within the zoning cap.
  • Check the funding gap — adjust debtFundingAed and equityFundingAed until sources cover uses.
  • If the returns or programme look off, revise the assumptions that are driving the issue and
    call compute_workbook again. Iterate as many times as needed to reach a coherent result.
  • If the workbook validation has unresolved issues after your final call, include them in warnings.

If the model is BTR, do not call compute_workbook. It is BTS-only. Instead:
  • Verify the unit mix and monthly rents are internally coherent.
  • Make sure the BTR assumptions are complete enough for a downstream rental operating model:
    `btrUnitConfigs`, occupancy, lease-up, rent growth, vacancy, OpEx, cap rates, and perm debt metrics.
  • Keep `unitConfigs` aligned with the BTR mix for area and parking math, but do not assign sales rates.

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


_BTS_PREFETCHED_SYSTEM_PROMPT = """\
You are a Dubai real estate development advisor producing an initial build-to-sell (BTS) \
feasibility study for a specific GIS plot. Your output seeds a developer's financial workbook.

Use only the plot dossier, BTS market context, land cost anchor, and default assumption scaffold \
included in the user message. Do not call tools; all required BTS context has already been \
prefetched before this run.

This is a Build-to-Sell residential model:
  • Use off-plan pricing as the primary sales-rate anchor.
  • Use existing-stock pricing as a floor and sanity check.
  • Use comparable projects to calibrate product tier, unit mix, and supply risk.
  • Anchor land cost to comparable land sales and the per-GFA-sqm sanity check.
  • Set a realistic residential unit mix that fits the max GFA and target buyer profile.
  • Set construction cost, soft costs, timeline, payment plan, debt, and equity assumptions.
  • Funding values should be coherent, but the server will run final workbook normalization after \
    your draft.

Return:
  headline:    one-line project description
  summary:     6-10 bullets covering site, programme, pricing rationale, cost, returns, and risks
  constraints: hard zoning/regulatory facts from the plot data
  warnings:    specific actionable risks, including missing evidence or weak assumptions
  assumptions: final FeasibilityAssumptions

A weak or loss-making result is acceptable. Flag it clearly and identify the sensitivity lever.
Never invent evidence. If evidence is absent, say so. Zoning and GFA constraints from plot data \
are absolute.\
"""


hbu_seed_agent_bts_prefetched = Agent(
    model,
    deps_type=HBUSeedDeps,
    output_type=HBUSeedDraft,
    model_settings={"temperature": 0.1},
    system_prompt=_BTS_PREFETCHED_SYSTEM_PROMPT,
)


_BTR_SYSTEM_PROMPT = """\
You are a Dubai CRE build-to-rent underwriting advisor producing an initial HBU feasibility study \
for a specific GIS plot.

Use only the plot dossier, BTR rental market context, land cost anchor, and default assumption \
scaffold included in the user message. Do not call tools; all required BTR context has already \
been prefetched before this run.

This is a Build-to-Rent model, not Build-to-Sell:
  • Do not use off-plan sales pricing, GDV, presales, or escrow logic to justify rental assumptions.
  • Anchor rents to the rental size-band evidence when available.
  • Every `btrUnitConfig` must use standard Dubai labels: "Studio", "1BR", "2BR", "3BR", "4BR+".
  • Every `btrUnitConfig` must have non-zero units, non-zero avgSizeSqm, and non-zero monthlyRentAed.
  • Keep `unitConfigs` aligned with `btrUnitConfigs` for area and parking math, but do not assign sales rates.
  • Focus on stabilized occupancy, rent growth, vacancy, OpEx, cap rates, permanent debt, and hold-period return logic.

Return:
  headline:    one-line project description
  summary:     6–10 bullets covering site, rental programme, rent evidence, cost, financing/returns, and risks
  constraints: hard zoning/regulatory facts from the plot data
  warnings:    specific actionable risks, including missing evidence or weak assumptions
  assumptions: final FeasibilityAssumptions

A weak or loss-making result is acceptable. Flag it clearly and identify the sensitivity lever.
Never invent evidence. If evidence is absent, say so. Zoning and GFA constraints from plot data are absolute.\
"""


hbu_seed_agent_btr = Agent(
    model,
    deps_type=HBUSeedDeps,
    output_type=HBUSeedDraft,
    model_settings={"temperature": 0.1},
    system_prompt=_BTR_SYSTEM_PROMPT,
)


@hbu_seed_agent.tool
async def get_existing_market_pricing(
    ctx: RunContext[HBUSeedDeps], usage: Usage = "unknown"
) -> list[dict]:
    """Secondary-market (existing stock) median transaction prices by unit type for this plot's area.

    Returns: list of {unit_type, transaction_count, median_price_sqm, avg_area_sqm}.
    Use as a pricing floor — existing stock typically trades below off-plan launch prices.
    Returns an empty list if no data is available for this area.
    """
    rows = await get_market_pricing(
        ctx.deps.market_area,
        _tool_usage(ctx, usage),
        stage="existing",
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_off_plan_market_pricing(
    ctx: RunContext[HBUSeedDeps], usage: Usage = "unknown"
) -> list[dict]:
    """Off-plan transaction prices segmented by unit type and months-to-handover horizon bucket.

    Returns: list of {unit_type, horizon_bucket, avg_months_to_completion, transaction_count,
    median_price_sqm, avg_area_sqm, last_transaction_date}.
    Select the bucket whose avg_months_to_completion is closest to your projected handover horizon.
    This is the primary source for selling rate assumptions.
    Returns an empty list if no off-plan data is available for this area.
    """
    rows = await get_off_plan_pricing_curve(
        ctx.deps.market_area,
        _tool_usage(ctx, usage),
        ctx.deps.scaffold.handoverDate,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_area_rental_market(ctx: RunContext[HBUSeedDeps]) -> dict:
    """Master-community rental averages for the selected plot area.

    Returns: {area_name, rental_contract_count_12m, median_annual_rent, avg_rent_price_sqm_12m,
    gross_yield_pct, top_developers, top_master_projects}.
    Use avg_rent_price_sqm_12m as the primary BTR rent anchor, then apply judgement from the
    comparable projects and plot positioning.
    """
    try:
        detail = await get_area_detail(ctx.deps.market_area)
    except ValueError:
        return {}

    return RentalMarketSummary(
        area_name=detail.area_name,
        rental_contract_count_12m=detail.rental_contract_count_12m,
        median_annual_rent=detail.median_annual_rent,
        avg_rent_price_sqm_12m=detail.avg_rent_price_sqm_12m,
        gross_yield_pct=detail.gross_yield_pct,
        top_developers=detail.top_developers,
        top_master_projects=detail.top_master_projects,
    ).model_dump()


@hbu_seed_agent.tool
async def get_rental_comparables(
    ctx: RunContext[HBUSeedDeps], usage: Usage = "unknown", limit: int = 6
) -> list[dict]:
    """Rental comparables ranked by similarity, enriched with achieved rent and yield metrics.

    Returns project name, score, achieved avg rent psqm, median annual rent, gross yield, and
    rental contract count. Use these comps to sanity-check the community rental average and decide
    a conservative BTR rental rate.
    """
    ranked = await rank_plot_comparables(
        ctx.deps.plot_details,
        _tool_usage(ctx, usage),
        "pricing",
        limit,
    )

    enriched: list[RentalComparableProject] = []
    for row in ranked:
        snapshot = await get_project_market_snapshot(row.project_id)
        enriched.append(
            RentalComparableProject(
                project_id=row.project_id,
                project_name=row.project_name,
                area_name=snapshot.area_name if snapshot else row.area_name,
                completion_status=snapshot.completion_status if snapshot else row.project_status,
                pipeline_status=snapshot.pipeline_status if snapshot else None,
                score=row.score,
                no_of_units=row.no_of_units,
                rental_contract_count_12m=snapshot.rental_contract_count_12m if snapshot else 0,
                median_annual_rent=snapshot.median_annual_rent if snapshot else None,
                avg_rent_price_sqm_12m=snapshot.avg_rent_price_sqm_12m if snapshot else None,
                gross_yield_pct=snapshot.gross_yield_pct if snapshot else None,
                rationale=list(row.rationale),
            )
        )
    return [row.model_dump() for row in enriched]


@hbu_seed_agent.tool
async def get_pricing_comparables(
    ctx: RunContext[HBUSeedDeps], usage: Usage = "unknown", limit: int = 6
) -> list[dict]:
    """Completed and actively selling projects ranked by similarity to this plot.

    Similarity scoring considers plot size, area, and usage. Returns project name, status,
    similarity score, median_price_sqm, dominant unit type, and total units.
    Use to cross-check selling rates and calibrate unit mix.
    """
    rows = await rank_plot_comparables(
        ctx.deps.plot_details,
        _tool_usage(ctx, usage),
        "pricing",
        limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_pipeline_comparables(
    ctx: RunContext[HBUSeedDeps], usage: Usage = "unknown", limit: int = 6
) -> list[dict]:
    """Planned and under-construction projects in the same market area.

    Returns project name, status, similarity score, total units, and land area.
    Use to gauge supply risk and identify unit type saturation in the pipeline.
    """
    rows = await rank_plot_comparables(
        ctx.deps.plot_details,
        _tool_usage(ctx, usage),
        "pipeline",
        limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def get_plot_land_sales(
    ctx: RunContext[HBUSeedDeps], days: int = 1825, limit: int = 12
) -> list[dict]:
    """Recent land sale transactions for plots of similar size in this area.

    Returns: list of {instance_date, area_name, plot_area_sqm, price_aed, price_sqm, price_per_gfa_sqm, project_name}.
    Use price_sqm (AED per plot sqm) to anchor landPricePsqm.
    Use price_per_gfa_sqm (AED per buildable GFA sqm, normalized to this plot's FAR) for FAR-adjusted comparison.
    A high price_per_gfa_sqm relative to AED/sqm GDV is a negative signal for viability.
    Consider the p25–p75 range as the credible window.
    An empty list means no land sales data is available — flag landPricePsqm as a critical warning.
    """
    plot = ctx.deps.plot_details
    t_far = (
        plot.far
        if plot.far and plot.far > 0
        else (
            plot.max_gfa_sqm / plot.plot_area_sqm
            if plot.plot_area_sqm > 0 and plot.max_gfa_sqm > 0
            else None
        )
    )
    rows = await get_land_sale_evidence(
        area_name=ctx.deps.market_area,
        plot_area_sqm=plot.plot_area_sqm,
        usage=ctx.deps.usage_override or plot.inferred_usage,
        target_far=t_far,
        days=days,
        limit=limit,
    )
    return [row.model_dump() for row in rows]


@hbu_seed_agent.tool
async def compute_workbook(
    ctx: RunContext[HBUSeedDeps], assumptions: FeasibilityAssumptions
) -> dict:
    """Run the financial model against the provided assumptions and return a summary.

    Returns: {success, summary} where summary contains gross_revenue_aed, total_costs_incl_vat_aed,
    gross_profit_aed, gross_margin_pct, off_plan_proceeds_aed, project_irr_pct, equity_irr_pct,
    modeled_gfa_sqm, total_units, funding_gap_aed, and a validation object.
    Use total_costs_incl_vat_aed and off_plan_proceeds_aed to set debt and equity funding amounts.
    """
    if ctx.deps.development_model == "build_to_rent_residential":
        return {
            "success": False,
            "error": "compute_workbook is BTS-only. Do not use it for build_to_rent_residential.",
        }
    workbook = compute_feasibility_workbook(ctx.deps.plot_details, assumptions, study=None)
    summary = compute_feasibility_summary(workbook)
    return {
        "success": True,
        "summary": summary.model_dump(mode="json"),
    }


async def generate_hbu_study(
    plot_number: str,
    usage_override: Usage | None = None,
    development_model: DevelopmentModel = "build_to_sell_residential",
) -> PlotResearch | None:
    details = await fetch_plot_details(plot_number)
    if details is None:
        return None

    usage = usage_override or details.inferred_usage
    market_area = await resolve_market_area(details.community_name)

    target_far = (
        details.far
        if details.far and details.far > 0
        else (
            details.max_gfa_sqm / details.plot_area_sqm
            if details.plot_area_sqm > 0 and details.max_gfa_sqm > 0
            else None
        )
    )
    competition_evidence, land_sales_evidence = await asyncio.gather(
        rank_plot_comparables(details, usage, "pipeline"),
        get_land_sale_evidence(
            area_name=market_area,
            plot_area_sqm=details.plot_area_sqm,
            usage=usage,
            target_far=target_far,
            days=1825,
            limit=12,
        ),
    )

    land_price_anchor = _land_price_anchor_psqm(
        land_sales_evidence,
        area_name=market_area or "",
        far=target_far or 0.0,
    )
    scaffold = build_assumptions_scaffold(
        details,
        usage,
        land_price_anchor_psqm=land_price_anchor,
        development_model=development_model,
    )

    market_pricing = []
    pricing_evidence = []
    off_plan_market_pricing = []
    off_plan_benchmarks = []
    off_plan_confidence = None
    rental_market_summary: RentalMarketSummary | None = None
    rental_comparables: list[RentalComparableProject] = []
    size_band_rates: list[RentalRateBySizeBand] = []

    if development_model == "build_to_rent_residential":
        # Fetch area summary, ranked comps, and size-band rates in parallel
        try:
            area_detail_result, ranked_rental_comps, size_band_rates = await asyncio.gather(
                get_area_detail(market_area),
                rank_plot_comparables(details, usage, "pricing"),
                get_rental_rates_by_size_band(market_area),
            )
            rental_market_summary = RentalMarketSummary(
                area_name=area_detail_result.area_name,
                rental_contract_count_12m=area_detail_result.rental_contract_count_12m,
                median_annual_rent=area_detail_result.median_annual_rent,
                avg_rent_price_sqm_12m=area_detail_result.avg_rent_price_sqm_12m,
                gross_yield_pct=area_detail_result.gross_yield_pct,
                top_developers=area_detail_result.top_developers,
                top_master_projects=area_detail_result.top_master_projects,
            )
        except ValueError:
            rental_market_summary = None
            ranked_rental_comps = await rank_plot_comparables(details, usage, "pricing")

        # Fetch all project snapshots in parallel (was serial — O(n) sequential awaits)
        snapshots = await asyncio.gather(
            *[get_project_market_snapshot(row.project_id) for row in ranked_rental_comps]
        )
        for row, snapshot in zip(ranked_rental_comps, snapshots):
            rental_comparables.append(
                RentalComparableProject(
                    project_id=row.project_id,
                    project_name=row.project_name,
                    area_name=snapshot.area_name if snapshot else row.area_name,
                    completion_status=snapshot.completion_status
                    if snapshot
                    else row.project_status,
                    pipeline_status=snapshot.pipeline_status if snapshot else None,
                    score=row.score,
                    no_of_units=row.no_of_units,
                    rental_contract_count_12m=snapshot.rental_contract_count_12m if snapshot else 0,
                    median_annual_rent=snapshot.median_annual_rent if snapshot else None,
                    avg_rent_price_sqm_12m=snapshot.avg_rent_price_sqm_12m if snapshot else None,
                    gross_yield_pct=snapshot.gross_yield_pct if snapshot else None,
                    rationale=list(row.rationale),
                )
            )
    else:
        market_pricing, pricing_evidence, off_plan_market_pricing = await asyncio.gather(
            get_market_pricing(market_area, usage, stage="existing"),
            rank_plot_comparables(details, usage, "pricing", limit=10),
            get_off_plan_pricing_curve(market_area, usage, scaffold.handoverDate),
        )
        target_horizon_months = max(
            1, round((date.fromisoformat(scaffold.handoverDate) - date.today()).days / 30)
        )
        fallback_prices = {row.unit_type: row.median_price_sqm for row in market_pricing}
        off_plan_benchmarks = build_off_plan_unit_benchmarks(
            off_plan_market_pricing, target_horizon_months, fallback_prices
        )
        off_plan_confidence = build_off_plan_pricing_confidence(
            off_plan_market_pricing, target_horizon_months
        )

    market_context_block = (
        (
            "=== BTR RENTAL MARKET CONTEXT ===\n"
            f"Master community rental summary: {json.dumps(rental_market_summary.model_dump(mode='json'), indent=2) if rental_market_summary else 'No area rental summary available.'}\n\n"
            "Rental rates by unit size band (use these to seed monthlyRentAed per config — each config should use the band matching its avgSizeSqm):\n"
            + (
                "\n".join(
                    f"  {b.unit_type_proxy} ({b.size_band_label}): AED {b.median_rent_psm_annual:,.0f}/sqm/yr, "
                    f"AED {b.median_annual_rent:,.0f} median annual rent, {b.contract_count} contracts"
                    for b in size_band_rates
                )
                or "  No size-band rental rates available — use blended area rate."
            )
            + "\n\nRental comparables:\n"
            + (
                "\n".join(
                    f"  {comp.project_name}: AED {comp.avg_rent_price_sqm_12m or 0:,.0f}/sqm/yr, "
                    f"AED {comp.median_annual_rent or 0:,.0f} median annual rent, "
                    f"{comp.rental_contract_count_12m} rental contracts, "
                    f"gross yield {comp.gross_yield_pct or 0:.1f}%"
                    for comp in rental_comparables
                )
                or "  No rental comparables available."
            )
        )
        if development_model == "build_to_rent_residential"
        else (
            "=== BTS MARKET CONTEXT ===\n"
            "Off-plan pricing benchmarks (primary sales-rate anchor):\n"
            + (
                "\n".join(
                    f"  {b.unit_type}: AED {b.selected_price_sqm:.0f}/sqm "
                    f"({b.confidence_label} confidence, {b.transaction_count} txns, {b.selected_horizon_bucket})"
                    for b in off_plan_benchmarks
                )
                or "  No off-plan benchmarks available — use existing market pricing."
            )
            + "\n\nExisting stock pricing floor:\n"
            + (
                "\n".join(
                    f"  {row.unit_type}: AED {row.median_price_sqm:,.0f}/sqm, "
                    f"{row.transaction_count} txns"
                    + (f", avg area {row.avg_area_sqm:,.0f} sqm" if row.avg_area_sqm else "")
                    for row in market_pricing
                )
                or "  No segmented existing-stock pricing available."
            )
            + "\n\nPricing comparables:\n"
            + (
                "\n".join(
                    f"  {comp.project_name}: {comp.project_status or 'unknown status'}, "
                    f"score {comp.score:.0f}, median AED {comp.median_price_sqm or 0:,.0f}/sqm, "
                    f"dominant unit {comp.dominant_unit_type or 'unknown'}, units {comp.no_of_units or 0}"
                    for comp in pricing_evidence[:8]
                )
                or "  No pricing comparable projects available."
            )
            + "\n\nPipeline and supply-risk comparables:\n"
            + (
                "\n".join(
                    f"  {comp.project_name}: {comp.project_status or 'unknown status'}, "
                    f"score {comp.score:.0f}, units {comp.no_of_units or 0}, "
                    f"land area {comp.total_land_area_sqm or 0:,.0f} sqm"
                    for comp in competition_evidence[:8]
                )
                or "  No pipeline comparable projects available."
            )
        )
    )

    prompt = (
        f"=== PLOT DOSSIER ===\n"
        f"{_plot_context(details)}\n\n"
        f"=== DEVELOPMENT MODEL ===\n"
        f"{development_model}\n\n"
        f"=== MARKET AREA ===\n"
        f"Use {market_area} as the canonical transaction area for pricing and land evidence.\n\n"
        f"{market_context_block}\n\n"
        f"=== LAND COST ANCHOR ===\n"
        f"{_land_anchor_summary(land_sales_evidence, details.plot_area_sqm, market_area)}\n\n"
        f"=== DEFAULT ASSUMPTION SCAFFOLD ===\n"
        f"Computed from the plot's GFA, height, and inferred usage. "
        f"Override any value where evidence supports a better estimate. "
        f"Unit configs, BTR configs when applicable, and funding amounts must be set by you.\n"
        f"{json.dumps(scaffold.model_dump(mode='json'), indent=2)}\n\n"
        f"Research the market, form your assumptions, and return the HBU study for "
        f"plot {plot_number} (usage: {usage}, development model: {development_model})."
    )

    agent = (
        hbu_seed_agent_btr
        if development_model == "build_to_rent_residential"
        else hbu_seed_agent_bts_prefetched
    )
    result = await agent.run(
        prompt,
        deps=HBUSeedDeps(
            plot_number=plot_number,
            plot_details=details,
            market_area=market_area,
            scaffold=scaffold,
            development_model=development_model,
            usage_override=usage_override,
        ),
        usage_limits=UsageLimits(
            request_limit=3 if development_model == "build_to_rent_residential" else 15
        ),
    )
    draft = result.output

    draft.assumptions = (
        _ensure_btr_assumptions(draft.assumptions, rental_market_summary, size_band_rates)
        if development_model == "build_to_rent_residential"
        else _ensure_bts_assumptions(draft.assumptions)
    )

    draft.assumptions, land_floor_warning = _enforce_land_price_floor(
        draft.assumptions,
        land_sales_evidence,
        details.plot_area_sqm,
        area_name=market_area or "",
        far=target_far or 0.0,
    )
    capital_stack_warning = None
    if development_model != "build_to_rent_residential":
        draft.assumptions, capital_stack_warning = _normalize_capital_stack(
            details, draft.assumptions
        )

    warnings = list(details.warnings)
    warnings.extend(item for item in draft.warnings if item not in warnings)
    if land_floor_warning and land_floor_warning not in warnings:
        warnings.append(land_floor_warning)
    if capital_stack_warning and capital_stack_warning not in warnings:
        warnings.append(capital_stack_warning)
    if development_model != "build_to_rent_residential" and not market_pricing:
        warnings.append("No segmented existing transaction pricing was found for this plot area.")
    if development_model != "build_to_rent_residential" and not off_plan_market_pricing:
        warnings.append("No off-plan pricing curve was found for this plot area.")
    if development_model == "build_to_rent_residential" and rental_market_summary is None:
        warnings.append("No master-community rental summary was found for this plot area.")
    if development_model == "build_to_rent_residential" and not rental_comparables:
        warnings.append("No rental comparable projects were found for this plot area.")

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
        market_area=market_area,
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
        rental_market_summary=rental_market_summary,
        rental_comparables=rental_comparables,
        rental_rates_by_size_band=size_band_rates,
        assumptions=draft.assumptions,
        warnings=warnings,
        land_cost_estimate_aed_low=land_cost_low,
        land_cost_estimate_aed_mid=land_cost_mid,
        land_cost_estimate_aed_high=land_cost_high,
    )
