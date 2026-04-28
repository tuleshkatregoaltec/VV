import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from app.feasibility.models import (
    FeasibilityAssumptions,
    FeasibilityCashFlowPeriod,
    FeasibilityCashFlowSummary,
    FeasibilityComputedSummary,
    FeasibilityCostLineItem,
    FeasibilityCostSummary,
    FeasibilityFinancingSummary,
    FeasibilityFundingSource,
    FeasibilityFundingSummary,
    FeasibilityProgramRow,
    FeasibilityProgramSummary,
    FeasibilityReturnsSummary,
    FeasibilityScheduleSummary,
    FeasibilitySiteEnvelope,
    FeasibilityWorkbook,
    PlotDetails,
    PlotResearch,
    Usage,
    ValidationIssue,
    ValidationSummary,
)

# Workbook Engine — mirrored against frontend/src/lib/feasibility/workbook/engine.ts
# Core contract: computeWorkbook(assumptions) -> outputs
# All calculations derive from assumptions. No external dependencies.


# Output Types


@dataclass(frozen=True)
class AreaOutputs:
    plotAreaSqm: float
    maxGfaSqm: float
    maxStoreys: int | None
    appliedCoveragePct: float
    buildableFootprintSqm: float
    builtUpAreaSqm: float
    modeledGfaSqm: float
    grossSaleableAreaSqm: float
    parkingBuaAllowanceSqm: float
    totalBuaSqm: float
    notes: list[str]


@dataclass(frozen=True)
class ProgramRowOutput:
    id: str
    label: str
    units: int
    avgSizeSqm: float
    totalAreaSqm: float
    sellingRatePsqm: float
    revenueAed: float
    parkingSpaces: float


@dataclass(frozen=True)
class ProgramOutputs:
    rows: list[ProgramRowOutput]
    totalUnits: int
    totalAreaSqm: float
    totalParkingSpaces: float
    grossRevenueAed: float
    weightedAvgSalesRatePsqm: float


@dataclass(frozen=True)
class CostOutputs:
    landAcquisitionAed: float
    landTransferFeeAed: float
    brokerageFeeAed: float
    legalDdCostAed: float
    totalLandCostAed: float
    constructionCostAed: float
    inflationCostAed: float
    constructionCostInclInflationAed: float
    designSupervisionCostAed: float
    marketingCostAed: float
    salesAgentFeesAed: float
    infrastructureCostAed: float
    governmentFeesAed: float
    masterCommunityFeesAed: float
    ffeOsePreopeningCostAed: float
    contingencyCostAed: float
    demolitionCostAed: float
    totalCostsExclVatAed: float
    vatAmountAed: float
    totalCostsInclVatAed: float


@dataclass(frozen=True)
class FundingOutputs:
    depositPct: float
    preHandoverPct: float
    handoverPct: float
    offPlanProceedsAed: float
    debtFundingAed: float
    equityFundingAed: float
    vatRefundsAed: float
    totalSourcesAed: float
    totalUsesAed: float
    gapAed: float
    landLoanCapacityAed: float
    constructionLoanCapacityAed: float
    totalDebtCapacityAed: float
    landLoanRatePct: float
    constructionLoanRatePct: float


@dataclass(frozen=True)
class CashFlowPeriodOutput:
    periodLabel: str
    periodEndDate: str
    revenueInflowsAed: float
    depositInflowsAed: float
    preHandoverInflowsAed: float
    handoverInflowsAed: float
    vatRefundInflowsAed: float
    operatingOutflowsAed: float
    costLandAed: float
    costConstructionAed: float
    costProfessionalFeesAed: float
    costMarketingAed: float
    costSalesAgentAed: float
    costInfrastructureAed: float
    costAuthorityFeesAed: float
    costCommunityFeesAed: float
    costContingencyAed: float
    costVatAed: float
    unleveredNetCashFlowAed: float
    debtDrawAed: float
    debtRepaymentAed: float
    interestPaidAed: float
    commitmentFeePaidAed: float
    equityContributionAed: float
    equityDistributionAed: float
    leveredNetCashFlowAed: float
    debtBalanceAed: float
    debtHeadroomAed: float
    landLoanBalanceAed: float
    constructionLoanBalanceAed: float
    costPaidFromEscrowAed: float
    escrowBalanceAed: float
    landDrawAed: float
    constructionDrawAed: float


@dataclass(frozen=True)
class CashFlowOutputs:
    periods: list[CashFlowPeriodOutput]
    totalRevenueAed: float
    totalCostsAed: float
    peakFundingAed: float


@dataclass(frozen=True)
class ReturnsOutputs:
    grossProfitAed: float
    grossMarginPct: float
    allInProjectCostAed: float
    allInProjectProfitAed: float
    allInMarginPct: float
    projectIrrPct: float | None
    projectMoic: float
    equityIrrPct: float | None
    equityMoic: float
    totalInterestPaidAed: float
    totalCommitmentFeesAed: float
    arrangementFeeAed: float
    peakDebtAed: float
    peakEquityAed: float


@dataclass(frozen=True)
class FinancingOutputs:
    baseProjectCostAed: float
    allInProjectCostAed: float
    allInCostToRevenuePct: float
    presaleCoveragePctAtConstruction: float
    requiredCompletionReserveAed: float
    completionReserveCoveragePct: float
    sponsorReleaseCapacityAed: float
    debtCommitmentUtilizationPct: float
    debtCommitmentAed: float
    peakDebtAed: float
    minDebtHeadroomAed: float
    arrangementFeeAed: float
    initialCommitmentFeeAed: float
    capitalizedInterestAed: float
    commitmentFeeCarryAed: float
    totalFinanceCostsAed: float
    equityContributedAed: float
    equityDistributedAed: float
    closingDebtBalanceAed: float
    closingEscrowBalanceAed: float


@dataclass(frozen=True)
class BudgetTimingPeriod:
    periodLabel: str
    periodEndDate: str
    budgetedCostsAed: float
    sellingCostsAed: float
    constructionRelatedCostsAed: float
    vatCostsAed: float


@dataclass(frozen=True)
class BudgetTimingOutputs:
    periods: list[BudgetTimingPeriod]
    totalBudgetedCostsAed: float


@dataclass(frozen=True)
class SourcesUsesRow:
    category: Literal["source", "use"]
    code: str
    label: str
    amountAed: float
    basis: str


@dataclass(frozen=True)
class SourcesUsesOutputs:
    sources: list[SourcesUsesRow]
    uses: list[SourcesUsesRow]
    totalSourcesAed: float
    totalUsesAed: float
    gapAed: float


@dataclass(frozen=True)
class WorkbookOutputs:
    area: AreaOutputs
    program: ProgramOutputs
    costs: CostOutputs
    funding: FundingOutputs
    cashFlow: CashFlowOutputs
    returns: ReturnsOutputs
    financing: FinancingOutputs
    budgetTiming: BudgetTimingOutputs
    sourcesUses: SourcesUsesOutputs


# Helpers


def round(value: float, digits: int = 2) -> float:
    factor = 10**digits
    scaled = value * factor
    rounded = math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)
    return rounded / factor


def parseIsoDate(s: str, fallback: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return fallback
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def addMonths(dt: datetime, months: int) -> datetime:
    year = dt.year + (dt.month - 1 + months) // 12
    month = (dt.month - 1 + months) % 12 + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def endOfMonth(d: datetime) -> datetime:
    if d.month == 12:
        return datetime(d.year + 1, 1, 1, tzinfo=timezone.utc).replace(day=1) - datetime.resolution
    return datetime(d.year, d.month + 1, 1, tzinfo=timezone.utc) - datetime.resolution


def iterMonthEnds(start: datetime, end: datetime) -> list[datetime]:
    cursor = endOfMonth(start)
    periods: list[datetime] = []
    while cursor < end:
        periods.append(cursor)
        cursor = endOfMonth(addMonths(cursor, 1))
    periods.append(endOfMonth(end))
    return [
        month_end
        for index, month_end in enumerate(periods)
        if index == 0 or month_end != periods[index - 1]
    ]


def periodicIrr(cashFlows: list[float], periodsPerYear: int) -> float | None:
    if not any(cf > 0 for cf in cashFlows) or not any(cf < 0 for cf in cashFlows):
        return None

    def npv(rate: float) -> float:
        return sum(cf / ((1 + rate) ** idx) for idx, cf in enumerate(cashFlows))

    rate = 0.05
    minRate = -0.9999
    maxRate = 5.0
    newtonConverged = False
    for _ in range(100):
        n = npv(rate)
        dn = sum(-(idx * cf) / ((1 + rate) ** (idx + 1)) for idx, cf in enumerate(cashFlows))
        if not all(map(_is_finite, [n, dn])):
            break
        if abs(dn) < 1e-10:
            break
        nextRate = rate - n / dn
        if not _is_finite(nextRate):
            break
        nextRate = max(min(nextRate, maxRate), minRate)
        if abs(nextRate - rate) < 1e-7:
            rate = nextRate
            newtonConverged = True
            break
        rate = nextRate
    if newtonConverged and minRate < rate < maxRate and _is_finite(rate):
        annualised = ((1 + rate) ** periodsPerYear - 1) * 100
        if _is_finite(annualised):
            return annualised

    lo = -0.999
    hi = 5.0
    npvLo = npv(lo)
    npvHi = npv(hi)
    if not all(map(_is_finite, [npvLo, npvHi])):
        return None
    if npvLo * npvHi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        npvMid = npv(mid)
        if abs(npvMid) < 1e-2 or hi - lo < 1e-8:
            rate = mid
            break
        if npvLo * npvMid < 0:
            hi = mid
            npvHi = npvMid
        else:
            lo = mid
            npvLo = npvMid
    annualised = ((1 + rate) ** periodsPerYear - 1) * 100
    return annualised if _is_finite(annualised) else None


@dataclass
class PeriodRevenue:
    deposit: float
    preHandover: float
    handover: float


def scurveWeights(n: int) -> list[float]:
    if n <= 1:
        return [1.0]
    k = 8.0 / max(n, 1)
    mid = (n - 1) / 2.0
    raw = []
    for i in range(n):
        x = 2.718281828459045 ** (k * (i - mid))
        raw.append(x / ((1 + x) ** 2))
    total = sum(raw) or 1.0
    return [w / total for w in raw]


def revenueByPeriod(
    monthEnds: list[datetime],
    salesStart: datetime,
    handover: datetime,
    salesPeriodMonths: int,
    depositRevenue: float,
    preHandoverRevenue: float,
    handoverRevenue: float,
    milestoneDate: datetime | None,
) -> dict[str, PeriodRevenue]:
    def key(d: datetime) -> str:
        return d.date().isoformat()

    result = {key(month_end): PeriodRevenue(0.0, 0.0, 0.0) for month_end in monthEnds}
    salesStartMe = endOfMonth(salesStart)
    salesEndMe = endOfMonth(addMonths(salesStart, salesPeriodMonths - 1))
    salesMonths = [month_end for month_end in monthEnds if salesStartMe <= month_end <= salesEndMe]
    if not salesMonths:
        salesMonths = [salesStartMe] if monthEnds else []
    weights = scurveWeights(len(salesMonths))
    handoverMe = endOfMonth(handover)
    handoverKey = key(handoverMe)
    lastPreHandoverMe = endOfMonth(addMonths(handover, -1))
    milestoneMe: datetime | None = None
    if milestoneDate is not None:
        candidate = endOfMonth(milestoneDate)
        if salesStartMe < candidate < handoverMe and key(candidate) in result:
            milestoneMe = candidate

    def addRev(
        periodEnd: datetime, deposit: float = 0.0, preHandover: float = 0.0, handover: float = 0.0
    ) -> None:
        existing = result.get(key(periodEnd))
        if existing is None:
            return
        result[key(periodEnd)] = PeriodRevenue(
            deposit=round(existing.deposit + deposit),
            preHandover=round(existing.preHandover + preHandover),
            handover=round(existing.handover + handover),
        )

    def allocateEvenly(
        periods: list[datetime], amount: float, field: Literal["deposit", "preHandover", "handover"]
    ) -> None:
        if amount <= 0 or not periods:
            return
        perPeriod = round(amount / len(periods))
        running = 0.0
        for index, periodEnd in enumerate(periods):
            allocated = perPeriod if index < len(periods) - 1 else round(amount - running)
            running = round(running + allocated)
            if field == "deposit":
                addRev(periodEnd, deposit=allocated)
            elif field == "preHandover":
                addRev(periodEnd, preHandover=allocated)
            else:
                addRev(periodEnd, handover=allocated)

    for idx, salePeriodEnd in enumerate(salesMonths):
        weight = weights[idx]
        cohortDeposit = round(depositRevenue * weight)
        cohortPreHandover = round(preHandoverRevenue * weight)
        cohortHandover = round(handoverRevenue * weight)
        addRev(salePeriodEnd, deposit=cohortDeposit)
        if cohortPreHandover > 0 and salePeriodEnd < handoverMe:
            if milestoneMe is not None:
                collectionPeriod = milestoneMe if salePeriodEnd <= milestoneMe else salePeriodEnd
                if collectionPeriod > lastPreHandoverMe:
                    collectionPeriod = lastPreHandoverMe
                addRev(collectionPeriod, preHandover=cohortPreHandover)
            else:
                collectionPeriods = [
                    month_end for month_end in monthEnds if salePeriodEnd < month_end < handoverMe
                ]
                if not collectionPeriods:
                    addRev(salePeriodEnd, preHandover=cohortPreHandover)
                else:
                    allocateEvenly(collectionPeriods, cohortPreHandover, "preHandover")
        addRev(handoverMe, handover=cohortHandover)

    totDep = sum(value.deposit for value in result.values())
    totPH = sum(value.preHandover for value in result.values())
    totHO = sum(value.handover for value in result.values())
    dDep = round(depositRevenue - totDep)
    dPH = round(preHandoverRevenue - totPH)
    dHO = round(handoverRevenue - totHO)
    if handoverKey in result and (dDep or dPH or dHO):
        prev = result[handoverKey]
        result[handoverKey] = PeriodRevenue(
            deposit=round(prev.deposit + dDep),
            preHandover=round(prev.preHandover + dPH),
            handover=round(prev.handover + dHO),
        )
    return result


# Area Chain Benchmarks


BuildingForm = Literal["low_rise", "mid_rise", "tower"]


@dataclass(frozen=True)
class RatioBand:
    low: float
    base: float
    high: float


@dataclass(frozen=True)
class AreaBenchmark:
    usage: Literal["residential", "commercial", "mixed_use"]
    buildingForm: BuildingForm
    coverageRatio: RatioBand
    buaToGfaEfficiency: RatioBand
    gfaToGsaEfficiency: RatioBand


AREA_BENCHMARKS = [
    AreaBenchmark(
        usage="residential",
        buildingForm="low_rise",
        coverageRatio=RatioBand(low=0.55, base=0.6, high=0.65),
        buaToGfaEfficiency=RatioBand(low=0.89, base=0.91, high=0.93),
        gfaToGsaEfficiency=RatioBand(low=0.8, base=0.84, high=0.87),
    ),
    AreaBenchmark(
        usage="residential",
        buildingForm="mid_rise",
        coverageRatio=RatioBand(low=0.4, base=0.45, high=0.5),
        buaToGfaEfficiency=RatioBand(low=0.85, base=0.88, high=0.9),
        gfaToGsaEfficiency=RatioBand(low=0.76, base=0.8, high=0.83),
    ),
    AreaBenchmark(
        usage="residential",
        buildingForm="tower",
        coverageRatio=RatioBand(low=0.35, base=0.38, high=0.4),
        buaToGfaEfficiency=RatioBand(low=0.83, base=0.86, high=0.88),
        gfaToGsaEfficiency=RatioBand(low=0.73, base=0.77, high=0.8),
    ),
    AreaBenchmark(
        usage="mixed_use",
        buildingForm="mid_rise",
        coverageRatio=RatioBand(low=0.4, base=0.44, high=0.5),
        buaToGfaEfficiency=RatioBand(low=0.85, base=0.88, high=0.9),
        gfaToGsaEfficiency=RatioBand(low=0.75, base=0.78, high=0.81),
    ),
    AreaBenchmark(
        usage="commercial",
        buildingForm="mid_rise",
        coverageRatio=RatioBand(low=0.35, base=0.42, high=0.45),
        buaToGfaEfficiency=RatioBand(low=0.84, base=0.87, high=0.89),
        gfaToGsaEfficiency=RatioBand(low=0.7, base=0.74, high=0.77),
    ),
]


def classifyBuildingForm(numberOfFloors: int) -> BuildingForm:
    if numberOfFloors <= 8:
        return "low_rise"
    if numberOfFloors <= 20:
        return "mid_rise"
    return "tower"


def getBenchmark(usage: Usage, numberOfFloors: int) -> AreaBenchmark:
    normalizedUsage: Literal["residential", "commercial", "mixed_use"]
    if usage in {"commercial", "mixed_use", "residential"}:
        normalizedUsage = usage
    else:
        normalizedUsage = "residential"
    buildingForm = classifyBuildingForm(numberOfFloors)
    return next(
        (
            benchmark
            for benchmark in AREA_BENCHMARKS
            if benchmark.usage == normalizedUsage and benchmark.buildingForm == buildingForm
        ),
        AREA_BENCHMARKS[0],
    )


# Calculation Modules


def computeArea(a: FeasibilityAssumptions) -> AreaOutputs:
    # numberOfFloors is the design intent; maxStoreys is the regulatory ceiling.
    # Cap the design floors at the zoning maximum if one is specified.
    effectiveFloors = (
        min(a.numberOfFloors, a.maxStoreys) if a.maxStoreys is not None else a.numberOfFloors
    )
    benchmark = getBenchmark(a.usage, effectiveFloors)
    appliedCoveragePct = min(
        a.maxCoveragePct if a.maxCoveragePct is not None else benchmark.coverageRatio.base * 100,
        benchmark.coverageRatio.base * 100,
    )
    buildableFootprintSqm = round(a.plotAreaSqm * (appliedCoveragePct / 100))
    builtUpAreaSqm = round(buildableFootprintSqm * max(effectiveFloors, 1))
    modeledGfaSqm = round(
        min(
            a.maxGfaSqm if a.maxGfaSqm > 0 else builtUpAreaSqm * benchmark.buaToGfaEfficiency.base,
            builtUpAreaSqm * benchmark.buaToGfaEfficiency.base,
        )
    )
    grossSaleableAreaSqm = round(modeledGfaSqm * benchmark.gfaToGsaEfficiency.base)
    totalParkingSpaces = sum(row.units * row.parkingRatio for row in a.unitConfigs)
    parkingBuaAllowanceSqm = round(totalParkingSpaces * 32.515)
    totalBuaSqm = round(modeledGfaSqm * a.buaMultiplier + parkingBuaAllowanceSqm)
    notes: list[str] = []
    if a.maxCoveragePct is not None:
        notes.append(
            f"Applied footprint ratio capped by GIS max coverage of {round(a.maxCoveragePct, 1):g}%."
        )
    else:
        notes.append("GIS max coverage missing, benchmark footprint ratios applied.")
    return AreaOutputs(
        plotAreaSqm=a.plotAreaSqm,
        maxGfaSqm=a.maxGfaSqm,
        maxStoreys=a.maxStoreys,
        appliedCoveragePct=round(appliedCoveragePct),
        buildableFootprintSqm=buildableFootprintSqm,
        builtUpAreaSqm=builtUpAreaSqm,
        modeledGfaSqm=modeledGfaSqm,
        grossSaleableAreaSqm=grossSaleableAreaSqm,
        parkingBuaAllowanceSqm=parkingBuaAllowanceSqm,
        totalBuaSqm=totalBuaSqm,
        notes=notes,
    )


def computeProgram(a: FeasibilityAssumptions) -> ProgramOutputs:
    rows = [
        ProgramRowOutput(
            id=row.id,
            label=row.label,
            units=row.units,
            avgSizeSqm=row.avgSizeSqm,
            totalAreaSqm=round(row.units * row.avgSizeSqm),
            sellingRatePsqm=row.sellingRatePsqm,
            revenueAed=round(row.units * row.avgSizeSqm * row.sellingRatePsqm),
            parkingSpaces=round(row.units * row.parkingRatio),
        )
        for row in a.unitConfigs
        if row.units > 0
    ]
    totalUnits = sum(row.units for row in rows)
    totalAreaSqm = sum(row.totalAreaSqm for row in rows)
    totalParkingSpaces = sum(row.parkingSpaces for row in rows)
    grossRevenueAed = sum(row.revenueAed for row in rows)
    weightedAvgSalesRatePsqm = round(grossRevenueAed / totalAreaSqm) if totalAreaSqm > 0 else 0.0
    return ProgramOutputs(
        rows=rows,
        totalUnits=totalUnits,
        totalAreaSqm=totalAreaSqm,
        totalParkingSpaces=totalParkingSpaces,
        grossRevenueAed=grossRevenueAed,
        weightedAvgSalesRatePsqm=weightedAvgSalesRatePsqm,
    )


def computeCosts(
    a: FeasibilityAssumptions, area: AreaOutputs, program: ProgramOutputs
) -> CostOutputs:
    landAcquisitionAed = (
        a.landAcquisitionCostOverrideAed
        if a.landAcquisitionCostOverrideAed is not None
        else round(a.plotAreaSqm * a.landPricePsqm)
    )
    landTransferFeeAed = round(landAcquisitionAed * 0.04)
    totalLandCostAed = round(
        landAcquisitionAed + landTransferFeeAed + a.brokerageFeeAed + a.legalDdCostAed
    )
    constructionCostAed = round(area.totalBuaSqm * a.constructionCostPsqmBua)
    inflationCostAed = round(constructionCostAed * (a.midPointInflationPct / 100))
    constructionCostInclInflationAed = (
        a.constructionCostOverrideAed
        if a.constructionCostOverrideAed is not None
        else round(constructionCostAed + inflationCostAed)
    )
    designSupervisionCostAed = (
        a.designSupervisionCostOverrideAed
        if a.designSupervisionCostOverrideAed is not None
        else round(constructionCostAed * (a.designSupervisionPct / 100))
    )
    marketingCostAed = (
        a.marketingCostOverrideAed
        if a.marketingCostOverrideAed is not None
        else round(program.grossRevenueAed * (a.marketingCostPct / 100))
    )
    salesAgentFeesAed = (
        a.salesAgentFeesOverrideAed
        if a.salesAgentFeesOverrideAed is not None
        else round(program.grossRevenueAed * (a.salesAgentFeePct / 100))
    )
    contingencyCostAed = (
        a.contingencyCostOverrideAed
        if a.contingencyCostOverrideAed is not None
        else round(constructionCostAed * (a.contingencyPct / 100))
    )
    demolitionCostAed = a.demolitionCostAed if a.demolitionEnabled else 0.0
    totalCostsExclVatAed = round(
        totalLandCostAed
        + constructionCostInclInflationAed
        + designSupervisionCostAed
        + marketingCostAed
        + salesAgentFeesAed
        + a.infrastructureCostAed
        + a.governmentFeesAed
        + a.masterCommunityFeesAed
        + a.ffeOsePreopeningCostAed
        + contingencyCostAed
        + demolitionCostAed
    )
    vatAmountAed = round(totalCostsExclVatAed * (a.vatPct / 100))
    totalCostsInclVatAed = round(totalCostsExclVatAed + vatAmountAed)
    return CostOutputs(
        landAcquisitionAed=landAcquisitionAed,
        landTransferFeeAed=landTransferFeeAed,
        brokerageFeeAed=a.brokerageFeeAed,
        legalDdCostAed=a.legalDdCostAed,
        totalLandCostAed=totalLandCostAed,
        constructionCostAed=constructionCostAed,
        inflationCostAed=inflationCostAed,
        constructionCostInclInflationAed=constructionCostInclInflationAed,
        designSupervisionCostAed=designSupervisionCostAed,
        marketingCostAed=marketingCostAed,
        salesAgentFeesAed=salesAgentFeesAed,
        infrastructureCostAed=a.infrastructureCostAed,
        governmentFeesAed=a.governmentFeesAed,
        masterCommunityFeesAed=a.masterCommunityFeesAed,
        ffeOsePreopeningCostAed=a.ffeOsePreopeningCostAed,
        contingencyCostAed=contingencyCostAed,
        demolitionCostAed=demolitionCostAed,
        totalCostsExclVatAed=totalCostsExclVatAed,
        vatAmountAed=vatAmountAed,
        totalCostsInclVatAed=totalCostsInclVatAed,
    )


def computeFunding(
    a: FeasibilityAssumptions, program: ProgramOutputs, costs: CostOutputs
) -> FundingOutputs:
    depositPct = a.paymentPlan.depositPct
    preHandoverPct = a.paymentPlan.constructionPct
    handoverPct = a.paymentPlan.handoverPct
    offPlanProceedsAed = round(program.grossRevenueAed * ((depositPct + preHandoverPct) / 100))
    totalDebtCapacityAed = round(costs.totalCostsInclVatAed * a.debtToCostRatio)
    landLoanCapacityAed = round(
        min(costs.landAcquisitionAed * (a.landLoanLtvPct / 100), totalDebtCapacityAed)
    )
    constructionLoanCapacityAed = round(max(totalDebtCapacityAed - landLoanCapacityAed, 0))
    debtFundingAed = a.debtFundingAed if a.debtFundingAed > 0 else totalDebtCapacityAed
    equityFundingAed = (
        a.equityFundingAed
        if a.equityFundingAed > 0
        else round(max(costs.totalCostsInclVatAed - debtFundingAed, 0))
    )
    vatRefundsAed = costs.vatAmountAed
    totalSourcesAed = round(offPlanProceedsAed + debtFundingAed + equityFundingAed + vatRefundsAed)
    totalUsesAed = costs.totalCostsInclVatAed
    gapAed = round(totalUsesAed - totalSourcesAed)
    landLoanRatePct = round(a.eiborRatePct + a.landLoanSpreadBps / 100, 2)
    constructionLoanRatePct = round(a.eiborRatePct + a.constructionLoanSpreadBps / 100, 2)
    return FundingOutputs(
        depositPct=depositPct,
        preHandoverPct=preHandoverPct,
        handoverPct=handoverPct,
        offPlanProceedsAed=offPlanProceedsAed,
        debtFundingAed=debtFundingAed,
        equityFundingAed=equityFundingAed,
        vatRefundsAed=vatRefundsAed,
        totalSourcesAed=totalSourcesAed,
        totalUsesAed=totalUsesAed,
        gapAed=gapAed,
        landLoanCapacityAed=landLoanCapacityAed,
        constructionLoanCapacityAed=constructionLoanCapacityAed,
        totalDebtCapacityAed=totalDebtCapacityAed,
        landLoanRatePct=landLoanRatePct,
        constructionLoanRatePct=constructionLoanRatePct,
    )


def computeCashFlow(
    a: FeasibilityAssumptions,
    costs: CostOutputs,
    funding: FundingOutputs,
    program: ProgramOutputs,
) -> CashFlowOutputs:
    salesStart = parseIsoDate(a.salesCommencementDate, datetime(2026, 6, 1, tzinfo=timezone.utc))
    constructionStartDate = parseIsoDate(
        a.constructionDate, datetime(2026, 7, 1, tzinfo=timezone.utc)
    )
    handoverDate = parseIsoDate(a.handoverDate, datetime(2029, 1, 1, tzinfo=timezone.utc))
    landAcqDate = parseIsoDate(a.landAcquisitionDate, salesStart)
    milestoneDateRaw = a.preHandoverMilestoneDate
    milestoneDate = (
        parseIsoDate(milestoneDateRaw, salesStart)
        if milestoneDateRaw and _can_parse_iso_date(milestoneDateRaw)
        else None
    )
    salesPeriodMonths = max(int(round(a.salesPeriodMonths)), 1)
    timelineStart = min(landAcqDate, salesStart, constructionStartDate)
    monthEnds = iterMonthEnds(timelineStart, handoverDate)
    landPeriodEnd = endOfMonth(landAcqDate)
    handoverMe = endOfMonth(handoverDate)
    constructionStartMe = endOfMonth(constructionStartDate)
    constructionActivePeriods = [
        month_end for month_end in monthEnds if constructionStartMe <= month_end < handoverMe
    ]
    constructionActiveCount = max(len(constructionActivePeriods), 1)
    grossRevenue = program.grossRevenueAed
    dep = round(grossRevenue * (funding.depositPct / 100))
    preHandover = round(grossRevenue * (funding.preHandoverPct / 100))
    handoverRev = round(grossRevenue * (funding.handoverPct / 100))
    revenueMap = revenueByPeriod(
        monthEnds,
        salesStart,
        handoverDate,
        salesPeriodMonths,
        dep,
        preHandover,
        handoverRev,
        milestoneDate,
    )
    constructionPool = (
        costs.constructionCostInclInflationAed
        + costs.designSupervisionCostAed
        + costs.infrastructureCostAed
        + costs.governmentFeesAed
        + costs.masterCommunityFeesAed
        + costs.ffeOsePreopeningCostAed
        + costs.demolitionCostAed
    )
    monthlyConstruction = round(constructionPool / constructionActiveCount)
    monthlyMarketing = round(
        (costs.marketingCostAed + costs.salesAgentFeesAed) / max(len(monthEnds), 1)
    )
    monthlyContingency = round(costs.contingencyCostAed / constructionActiveCount)
    monthlyVat = round(costs.vatAmountAed / constructionActiveCount)
    annualRate = constructionLoanRatePctValue(a) / 100
    monthlyRate = annualRate / 12
    commitmentRate = a.commitmentFeePct / 100 / 12
    debtLimit = funding.debtFundingAed
    cashFlowPeriods: list[CashFlowPeriodOutput] = []
    debtBalance = 0.0
    escrowBalance = 0.0
    lastPeriodEnd = monthEnds[-1] if monthEnds else handoverMe
    for periodEnd in monthEnds:
        rev = revenueMap.get(periodEnd.date().isoformat(), PeriodRevenue(0.0, 0.0, 0.0))
        depositInflows = rev.deposit
        preHandoverInflows = rev.preHandover
        currentHandoverInflow = rev.handover
        revenueInflows = round(depositInflows + preHandoverInflows + currentHandoverInflow)
        constructionActive = constructionStartMe <= periodEnd < handoverMe
        costLand = costs.landAcquisitionAed if periodEnd == landPeriodEnd else 0.0
        costConstruction = monthlyConstruction if constructionActive else 0.0
        costContingency = monthlyContingency if constructionActive else 0.0
        costVat = monthlyVat if constructionActive else 0.0
        operatingOutflows = round(
            costLand + costConstruction + monthlyMarketing + costContingency + costVat
        )
        isLast = periodEnd == lastPeriodEnd
        vatRefundInflow = costs.vatAmountAed if isLast else 0.0
        cashBeforeDebt = escrowBalance + revenueInflows - operatingOutflows
        debtDraw = 0.0
        if cashBeforeDebt < 0:
            debtDraw = min(-cashBeforeDebt, max(debtLimit - debtBalance, 0))
        commitmentFeePaid = round(max(debtLimit - debtBalance, 0) * commitmentRate)
        interestPaid = round(max(debtBalance, 0) * monthlyRate)
        debtBalance = round(debtBalance + debtDraw + interestPaid + commitmentFeePaid)
        cashAfterDebt = escrowBalance + revenueInflows + debtDraw - operatingOutflows
        debtRepayment = 0.0
        if isLast or a.debtRepaymentMode == "sales_sweep":
            debtRepayment = round(min(max(cashAfterDebt, 0), debtBalance))
            debtBalance = round(debtBalance - debtRepayment)
        escrowBalance = round(cashAfterDebt - debtRepayment)
        equityContribution = 0.0
        if escrowBalance < 0:
            equityContribution = round(-escrowBalance)
            escrowBalance = 0.0
        equityDistribution = 0.0
        if isLast and escrowBalance > 0:
            equityDistribution = round(max(escrowBalance * (1 - a.escrowRetentionPct / 100), 0))
            escrowBalance = round(escrowBalance - equityDistribution)
        cashFlowPeriods.append(
            CashFlowPeriodOutput(
                periodLabel=periodEnd.strftime("%b %Y"),
                periodEndDate=periodEnd.date().isoformat(),
                revenueInflowsAed=revenueInflows,
                depositInflowsAed=depositInflows,
                preHandoverInflowsAed=preHandoverInflows,
                handoverInflowsAed=currentHandoverInflow,
                vatRefundInflowsAed=vatRefundInflow,
                operatingOutflowsAed=operatingOutflows,
                costLandAed=costLand,
                costConstructionAed=costConstruction,
                costProfessionalFeesAed=0.0,
                costMarketingAed=monthlyMarketing,
                costSalesAgentAed=0.0,
                costInfrastructureAed=0.0,
                costAuthorityFeesAed=0.0,
                costCommunityFeesAed=0.0,
                costContingencyAed=costContingency,
                costVatAed=costVat,
                unleveredNetCashFlowAed=round(revenueInflows + vatRefundInflow - operatingOutflows),
                debtDrawAed=round(debtDraw),
                debtRepaymentAed=debtRepayment,
                interestPaidAed=interestPaid,
                commitmentFeePaidAed=commitmentFeePaid,
                equityContributionAed=equityContribution,
                equityDistributionAed=equityDistribution,
                leveredNetCashFlowAed=round(
                    revenueInflows
                    - operatingOutflows
                    + debtDraw
                    - debtRepayment
                    - equityContribution
                    + equityDistribution
                ),
                debtBalanceAed=round(debtBalance),
                debtHeadroomAed=round(max(debtLimit - debtBalance, 0)),
                landLoanBalanceAed=round(min(debtBalance, funding.debtFundingAed * 0.35)),
                constructionLoanBalanceAed=round(
                    max(debtBalance - funding.debtFundingAed * 0.35, 0)
                ),
                costPaidFromEscrowAed=0.0,
                escrowBalanceAed=escrowBalance,
                landDrawAed=round(min(debtDraw, costLand)),
                constructionDrawAed=round(max(debtDraw - costLand, 0)),
            )
        )
    totalRevenueAed = dep + preHandover + handoverRev
    totalCostsAed = costs.totalCostsInclVatAed
    peakFundingAed = abs(min((period.escrowBalanceAed for period in cashFlowPeriods), default=0.0))
    return CashFlowOutputs(
        periods=cashFlowPeriods,
        totalRevenueAed=totalRevenueAed,
        totalCostsAed=totalCostsAed,
        peakFundingAed=peakFundingAed,
    )


def constructionLoanRatePctValue(a: FeasibilityAssumptions) -> float:
    return a.eiborRatePct + a.constructionLoanSpreadBps / 100


def computeReturns(
    a: FeasibilityAssumptions,
    program: ProgramOutputs,
    costs: CostOutputs,
    funding: FundingOutputs,
    periods: list[CashFlowPeriodOutput],
) -> ReturnsOutputs:
    projectCashflows = [period.unleveredNetCashFlowAed for period in periods]
    equityCashflows = [
        -period.equityContributionAed + period.equityDistributionAed for period in periods
    ]
    projectIrrPct = periodicIrr(projectCashflows, 12)
    equityIrrPct = periodicIrr(equityCashflows, 12)
    totalInterestPaidAed = round(sum(period.interestPaidAed for period in periods))
    totalCommitmentFeesAed = round(sum(period.commitmentFeePaidAed for period in periods))
    arrangementFeeAed = round(funding.debtFundingAed * (a.arrangementFeePct / 100))
    grossProfitAed = round(program.grossRevenueAed - costs.totalCostsInclVatAed)
    grossMarginPct = (
        round((grossProfitAed / program.grossRevenueAed) * 100)
        if program.grossRevenueAed > 0
        else 0.0
    )
    allInProjectCostAed = round(
        costs.totalCostsInclVatAed
        + totalInterestPaidAed
        + totalCommitmentFeesAed
        + arrangementFeeAed
    )
    allInProjectProfitAed = round(program.grossRevenueAed - allInProjectCostAed)
    allInMarginPct = (
        round((allInProjectProfitAed / program.grossRevenueAed) * 100)
        if program.grossRevenueAed > 0
        else 0.0
    )
    projectMoic = (
        round(program.grossRevenueAed / costs.totalCostsInclVatAed, 3)
        if costs.totalCostsInclVatAed > 0
        else 0.0
    )
    totalEquityContributed = round(sum(period.equityContributionAed for period in periods))
    totalEquityDistributed = round(sum(period.equityDistributionAed for period in periods))
    equityMoic = (
        round(totalEquityDistributed / totalEquityContributed, 3)
        if totalEquityContributed > 0
        else 0.0
    )
    peakDebtAed = max((period.debtBalanceAed for period in periods), default=0.0)
    peakEquityAed = max((period.equityContributionAed for period in periods), default=0.0)
    return ReturnsOutputs(
        grossProfitAed=grossProfitAed,
        grossMarginPct=grossMarginPct,
        allInProjectCostAed=allInProjectCostAed,
        allInProjectProfitAed=allInProjectProfitAed,
        allInMarginPct=allInMarginPct,
        projectIrrPct=round(projectIrrPct) if projectIrrPct is not None else None,
        projectMoic=projectMoic,
        equityIrrPct=round(equityIrrPct) if equityIrrPct is not None else None,
        equityMoic=equityMoic,
        totalInterestPaidAed=totalInterestPaidAed,
        totalCommitmentFeesAed=totalCommitmentFeesAed,
        arrangementFeeAed=arrangementFeeAed,
        peakDebtAed=peakDebtAed,
        peakEquityAed=peakEquityAed,
    )


def computeFinancing(
    a: FeasibilityAssumptions,
    funding: FundingOutputs,
    costs: CostOutputs,
    program: ProgramOutputs,
    periods: list[CashFlowPeriodOutput],
) -> FinancingOutputs:
    peakDebtAed = max((period.debtBalanceAed for period in periods), default=0.0)
    minDebtHeadroomAed = (
        min(period.debtHeadroomAed for period in periods) if periods else funding.debtFundingAed
    )
    arrangementFeeAed = round(funding.debtFundingAed * (a.arrangementFeePct / 100))
    initialCommitmentFeeAed = round(funding.debtFundingAed * (a.commitmentFeePct / 100))
    capitalizedInterestAed = round(sum(period.interestPaidAed for period in periods))
    commitmentFeeCarryAed = round(sum(period.commitmentFeePaidAed for period in periods))
    totalFinanceCostsAed = round(
        arrangementFeeAed + initialCommitmentFeeAed + capitalizedInterestAed + commitmentFeeCarryAed
    )
    finalPeriod = periods[-1] if periods else None
    presalesAtConstructionStart = round(program.grossRevenueAed * (funding.depositPct / 100))
    return FinancingOutputs(
        baseProjectCostAed=costs.totalCostsInclVatAed,
        allInProjectCostAed=round(costs.totalCostsInclVatAed + totalFinanceCostsAed),
        allInCostToRevenuePct=(
            round(
                ((costs.totalCostsInclVatAed + totalFinanceCostsAed) / program.grossRevenueAed)
                * 100
            )
            if program.grossRevenueAed > 0
            else 0.0
        ),
        presaleCoveragePctAtConstruction=(
            round((presalesAtConstructionStart / program.grossRevenueAed) * 100)
            if program.grossRevenueAed > 0
            else 0.0
        ),
        requiredCompletionReserveAed=round(program.grossRevenueAed * (a.escrowRetentionPct / 100)),
        completionReserveCoveragePct=round(
            (
                (finalPeriod.escrowBalanceAed if finalPeriod else 0.0)
                / max(program.grossRevenueAed * (a.escrowRetentionPct / 100), 1)
            )
            * 100
        ),
        sponsorReleaseCapacityAed=round(sum(period.equityDistributionAed for period in periods)),
        debtCommitmentUtilizationPct=(
            round((peakDebtAed / funding.debtFundingAed) * 100)
            if funding.debtFundingAed > 0
            else 0.0
        ),
        debtCommitmentAed=funding.debtFundingAed,
        peakDebtAed=peakDebtAed,
        minDebtHeadroomAed=minDebtHeadroomAed,
        arrangementFeeAed=arrangementFeeAed,
        initialCommitmentFeeAed=initialCommitmentFeeAed,
        capitalizedInterestAed=capitalizedInterestAed,
        commitmentFeeCarryAed=commitmentFeeCarryAed,
        totalFinanceCostsAed=totalFinanceCostsAed,
        equityContributedAed=round(sum(period.equityContributionAed for period in periods)),
        equityDistributedAed=round(sum(period.equityDistributionAed for period in periods)),
        closingDebtBalanceAed=finalPeriod.debtBalanceAed if finalPeriod else 0.0,
        closingEscrowBalanceAed=finalPeriod.escrowBalanceAed if finalPeriod else 0.0,
    )


def computeBudgetTiming(periods: list[CashFlowPeriodOutput]) -> BudgetTimingOutputs:
    budgetPeriods = [
        BudgetTimingPeriod(
            periodLabel=period.periodLabel,
            periodEndDate=period.periodEndDate,
            budgetedCostsAed=round(period.operatingOutflowsAed),
            sellingCostsAed=round(period.costMarketingAed + period.costSalesAgentAed),
            constructionRelatedCostsAed=round(
                period.costConstructionAed + period.costContingencyAed
            ),
            vatCostsAed=period.costVatAed,
        )
        for period in periods
    ]
    return BudgetTimingOutputs(
        periods=budgetPeriods,
        totalBudgetedCostsAed=round(sum(period.operatingOutflowsAed for period in periods)),
    )


def computeSourcesUses(funding: FundingOutputs, costs: CostOutputs) -> SourcesUsesOutputs:
    sources = [
        SourcesUsesRow(
            category="source",
            code="off_plan",
            label="Off-plan proceeds",
            amountAed=funding.offPlanProceedsAed,
            basis="deposit + pre-handover collections",
        ),
        SourcesUsesRow(
            category="source",
            code="debt",
            label="Senior debt",
            amountAed=funding.debtFundingAed,
            basis="debt-to-cost ratio",
        ),
        SourcesUsesRow(
            category="source",
            code="equity",
            label="Sponsor equity",
            amountAed=funding.equityFundingAed,
            basis="balancing source",
        ),
        SourcesUsesRow(
            category="source",
            code="vat_refund",
            label="VAT refunds",
            amountAed=funding.vatRefundsAed,
            basis="input tax recovery",
        ),
    ]
    uses = [
        SourcesUsesRow(
            category="use",
            code="land",
            label="Land acquisition",
            amountAed=costs.landAcquisitionAed,
            basis="plot area x land rate",
        ),
        SourcesUsesRow(
            category="use",
            code="construction",
            label="Construction",
            amountAed=costs.constructionCostInclInflationAed,
            basis="built-up area x construction rate",
        ),
        SourcesUsesRow(
            category="use",
            code="design",
            label="Design and supervision",
            amountAed=costs.designSupervisionCostAed,
            basis="% of construction",
        ),
        SourcesUsesRow(
            category="use",
            code="marketing",
            label="Marketing",
            amountAed=costs.marketingCostAed,
            basis="% of revenue",
        ),
        SourcesUsesRow(
            category="use",
            code="sales_agent",
            label="Sales agent fees",
            amountAed=costs.salesAgentFeesAed,
            basis="% of revenue",
        ),
        SourcesUsesRow(
            category="use",
            code="infrastructure",
            label="Infrastructure",
            amountAed=costs.infrastructureCostAed,
            basis="input",
        ),
        SourcesUsesRow(
            category="use",
            code="authority",
            label="Authority fees",
            amountAed=costs.governmentFeesAed,
            basis="input",
        ),
        SourcesUsesRow(
            category="use",
            code="community",
            label="Master community fees",
            amountAed=costs.masterCommunityFeesAed,
            basis="input",
        ),
        SourcesUsesRow(
            category="use",
            code="contingency",
            label="Contingency",
            amountAed=costs.contingencyCostAed,
            basis="% of non-land costs",
        ),
        SourcesUsesRow(
            category="use",
            code="vat",
            label="VAT",
            amountAed=costs.vatAmountAed,
            basis="% of total costs",
        ),
    ]
    return SourcesUsesOutputs(
        sources=sources,
        uses=uses,
        totalSourcesAed=funding.totalSourcesAed,
        totalUsesAed=costs.totalCostsInclVatAed,
        gapAed=round(costs.totalCostsInclVatAed - funding.totalSourcesAed),
    )


# Main Entry Point


def computeWorkbook(assumptions: FeasibilityAssumptions) -> WorkbookOutputs:
    area = computeArea(assumptions)
    program = computeProgram(assumptions)
    costs = computeCosts(assumptions, area, program)
    funding = computeFunding(assumptions, program, costs)
    cashFlow = computeCashFlow(assumptions, costs, funding, program)
    financing = computeFinancing(assumptions, funding, costs, program, cashFlow.periods)
    returns = computeReturns(assumptions, program, costs, funding, cashFlow.periods)
    budgetTiming = computeBudgetTiming(cashFlow.periods)
    sourcesUses = computeSourcesUses(funding, costs)
    return WorkbookOutputs(
        area=area,
        program=program,
        costs=costs,
        funding=funding,
        cashFlow=cashFlow,
        returns=returns,
        financing=financing,
        budgetTiming=budgetTiming,
        sourcesUses=sourcesUses,
    )


def validateWorkbook(
    assumptions: FeasibilityAssumptions,
    outputs: WorkbookOutputs,
) -> ValidationSummary:
    issues: list[ValidationIssue] = []

    if outputs.program.totalUnits == 0:
        issues.append(
            ValidationIssue(
                code="no_units",
                severity="warning",
                message="No unit mix configured",
                field="unitConfigs",
            )
        )
    if outputs.program.grossRevenueAed == 0 and outputs.program.totalUnits > 0:
        issues.append(
            ValidationIssue(
                code="zero_revenue",
                severity="warning",
                message="Revenue is zero despite having units",
                field="unitConfigs",
            )
        )
    if abs(outputs.funding.gapAed) > 1000:
        issues.append(
            ValidationIssue(
                code="funding_gap",
                severity="hard_fail" if outputs.funding.gapAed > 0 else "warning",
                message=f"Funding gap of AED {int(round(outputs.funding.gapAed)):,}",
                field="funding",
            )
        )
    if outputs.returns.grossMarginPct < 0:
        issues.append(
            ValidationIssue(
                code="negative_margin",
                severity="hard_fail",
                message="Project has negative gross margin",
                field="returns",
            )
        )
    if (
        outputs.costs.landAcquisitionAed == 0
        and assumptions.landPricePsqm == 0
        and assumptions.landAcquisitionCostOverrideAed is None
    ):
        issues.append(
            ValidationIssue(
                code="missing_land_cost",
                severity="missing_evidence",
                message="Land acquisition cost not set",
                field="landPricePsqm",
            )
        )
    if (
        outputs.costs.constructionCostAed == 0
        and assumptions.constructionCostPsqmBua == 0
        and assumptions.constructionCostOverrideAed is None
    ):
        issues.append(
            ValidationIssue(
                code="missing_construction_cost",
                severity="missing_evidence",
                message="Construction cost not set",
                field="constructionCostPsqmBua",
            )
        )
    hard_failures = sum(1 for issue in issues if issue.severity == "hard_fail")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    missing_evidence = sum(1 for issue in issues if issue.severity == "missing_evidence")
    status: Literal["ready", "needs_review", "invalid"] = "ready"
    if hard_failures > 0:
        status = "invalid"
    elif warnings > 0 or missing_evidence > 0:
        status = "needs_review"
    return ValidationSummary(
        status=status,
        hard_failures=hard_failures,
        warnings=warnings,
        missing_evidence=missing_evidence,
        issues=issues,
    )


def compute_feasibility_workbook(
    plot: PlotDetails,
    assumptions: FeasibilityAssumptions,
    study: PlotResearch | None = None,
) -> FeasibilityWorkbook:
    outputs = computeWorkbook(assumptions)
    validation = validateWorkbook(assumptions, outputs)

    site = FeasibilitySiteEnvelope(
        plot_number=plot.plot_number,
        community_name=plot.community_name,
        project_name=plot.project_name,
        permitted_use=assumptions.usage,
        plot_area_sqm=outputs.area.plotAreaSqm,
        max_gfa_sqm=outputs.area.maxGfaSqm,
        max_storeys=outputs.area.maxStoreys,
        far=round(assumptions.maxFar, 4),
        applied_coverage_pct=outputs.area.appliedCoveragePct,
        buildable_footprint_sqm=outputs.area.buildableFootprintSqm,
        built_up_area_sqm=outputs.area.builtUpAreaSqm,
        modeled_gfa_sqm=outputs.area.modeledGfaSqm,
        gross_saleable_area_sqm=outputs.area.grossSaleableAreaSqm,
        gfa_from_bua_efficiency_pct=round(
            (outputs.area.modeledGfaSqm / max(outputs.area.builtUpAreaSqm, 1)) * 100
        )
        if outputs.area.builtUpAreaSqm > 0
        else None,
        gsa_from_gfa_efficiency_pct=round(
            (outputs.area.grossSaleableAreaSqm / max(outputs.area.modeledGfaSqm, 1)) * 100
        )
        if outputs.area.modeledGfaSqm > 0
        else None,
        max_height=plot.max_height,
        max_coverage=plot.max_coverage,
        gfa_type=plot.gfa_type,
        site_plan_issue_date=plot.site_plan_issue_date,
        site_plan_expiry_date=plot.site_plan_expiry_date,
        is_verified=plot.is_verified,
        area_assumption_notes=list(outputs.area.notes),
        warnings=list(plot.warnings),
    )

    program = FeasibilityProgramSummary(
        usage=assumptions.usage,
        market_area=study.market_area if study else plot.community_name,
        headline=study.headline
        if study and study.headline
        else f"Feasibility study for plot {plot.plot_number}",
        gfa_sqm=outputs.area.modeledGfaSqm,
        saleable_area_sqm=outputs.program.totalAreaSqm,
        saleable_efficiency_pct=round(
            (outputs.program.totalAreaSqm / max(outputs.area.modeledGfaSqm, 1)) * 100
        )
        if outputs.area.modeledGfaSqm > 0
        else 0.0,
        total_units=outputs.program.totalUnits,
        total_parking_spaces=outputs.program.totalParkingSpaces,
        weighted_avg_sales_rate_aed_per_sqm=outputs.program.weightedAvgSalesRatePsqm,
        gross_revenue_aed=outputs.program.grossRevenueAed,
        rows=[
            FeasibilityProgramRow(
                unit_type=row.label,
                share_pct=round((row.totalAreaSqm / max(outputs.program.totalAreaSqm, 1)) * 100, 1)
                if outputs.program.totalAreaSqm > 0
                else 0.0,
                suggested_units=row.units,
                avg_size_sqm=row.avgSizeSqm,
                saleable_area_sqm=row.totalAreaSqm,
                sales_rate_aed_per_sqm=row.sellingRatePsqm,
                gross_revenue_aed=row.revenueAed,
                parking_ratio=round(row.parkingSpaces / max(row.units, 1), 2)
                if row.units > 0
                else 0.0,
                parking_spaces=row.parkingSpaces,
            )
            for row in outputs.program.rows
        ],
        warnings=list(study.warnings) if study else [],
    )

    cost_line_items = [
        FeasibilityCostLineItem(
            code="land",
            label="Land acquisition",
            amount_aed=outputs.costs.landAcquisitionAed,
            basis="plot area x land rate",
            basis_value=assumptions.plotAreaSqm,
            basis_unit="sqm",
            source="evidence",
            timing_rule="land_acquisition",
            timing_group="land",
        ),
        FeasibilityCostLineItem(
            code="land_transfer",
            label="Land transfer fee",
            amount_aed=outputs.costs.landTransferFeeAed,
            basis="4% of land acquisition",
            basis_value=4.0,
            basis_unit="%",
            source="derived",
            timing_rule="land_acquisition",
            timing_group="land",
        ),
        FeasibilityCostLineItem(
            code="brokerage",
            label="Brokerage",
            amount_aed=outputs.costs.brokerageFeeAed,
            basis="input",
            source="input",
            timing_rule="land_acquisition",
            timing_group="land",
        ),
        FeasibilityCostLineItem(
            code="legal_dd",
            label="Legal and due diligence",
            amount_aed=outputs.costs.legalDdCostAed,
            basis="input",
            source="input",
            timing_rule="land_acquisition",
            timing_group="land",
        ),
        FeasibilityCostLineItem(
            code="construction",
            label="Construction",
            amount_aed=outputs.costs.constructionCostInclInflationAed,
            basis="built-up area x construction rate",
            basis_value=outputs.area.totalBuaSqm,
            basis_unit="sqm",
            source="heuristic",
            timing_rule="construction_straight_line",
            timing_group="hard_cost",
        ),
        FeasibilityCostLineItem(
            code="design",
            label="Design and supervision",
            amount_aed=outputs.costs.designSupervisionCostAed,
            basis="% of construction",
            basis_value=assumptions.designSupervisionPct,
            basis_unit="%",
            source="derived",
            timing_rule="construction_straight_line",
            timing_group="professional_fees",
        ),
        FeasibilityCostLineItem(
            code="marketing",
            label="Marketing",
            amount_aed=outputs.costs.marketingCostAed,
            basis="% of revenue",
            basis_value=assumptions.marketingCostPct,
            basis_unit="%",
            source="derived",
            timing_rule="sales_velocity",
            timing_group="selling_costs",
        ),
        FeasibilityCostLineItem(
            code="sales_agent",
            label="Sales agent fees",
            amount_aed=outputs.costs.salesAgentFeesAed,
            basis="% of revenue",
            basis_value=assumptions.salesAgentFeePct,
            basis_unit="%",
            source="derived",
            timing_rule="sales_velocity",
            timing_group="selling_costs",
        ),
        FeasibilityCostLineItem(
            code="infrastructure",
            label="Infrastructure",
            amount_aed=outputs.costs.infrastructureCostAed,
            basis="input",
            source="input",
            timing_rule="construction_straight_line",
            timing_group="authority_and_infrastructure",
        ),
        FeasibilityCostLineItem(
            code="authority",
            label="Authority fees",
            amount_aed=outputs.costs.governmentFeesAed,
            basis="input",
            source="input",
            timing_rule="construction_straight_line",
            timing_group="authority_and_infrastructure",
        ),
        FeasibilityCostLineItem(
            code="community",
            label="Master community fees",
            amount_aed=outputs.costs.masterCommunityFeesAed,
            basis="input",
            source="input",
            timing_rule="construction_straight_line",
            timing_group="authority_and_infrastructure",
        ),
        FeasibilityCostLineItem(
            code="ffe_ose",
            label="FFE / OSE / pre-opening",
            amount_aed=outputs.costs.ffeOsePreopeningCostAed,
            basis="input",
            source="input",
            timing_rule="construction_straight_line",
            timing_group="other",
        ),
        FeasibilityCostLineItem(
            code="contingency",
            label="Contingency",
            amount_aed=outputs.costs.contingencyCostAed,
            basis="% of construction",
            basis_value=assumptions.contingencyPct,
            basis_unit="%",
            source="derived",
            timing_rule="construction_straight_line",
            timing_group="contingency",
        ),
        FeasibilityCostLineItem(
            code="demolition",
            label="Demolition",
            amount_aed=outputs.costs.demolitionCostAed,
            basis="input",
            source="input",
            timing_rule="construction_straight_line",
            timing_group="other",
        ),
    ]

    costs = FeasibilityCostSummary(
        total_costs_excl_vat_aed=outputs.costs.totalCostsExclVatAed,
        vat_amount_aed=outputs.costs.vatAmountAed,
        total_costs_incl_vat_aed=outputs.costs.totalCostsInclVatAed,
        cost_to_revenue_pct=round(
            (outputs.costs.totalCostsInclVatAed / outputs.program.grossRevenueAed) * 100
        )
        if outputs.program.grossRevenueAed > 0
        else 0.0,
        gross_profit_aed=outputs.returns.grossProfitAed,
        gross_margin_pct=outputs.returns.grossMarginPct,
        line_items=cost_line_items,
    )

    funding = FeasibilityFundingSummary(
        deposit_pct=outputs.funding.depositPct,
        pre_handover_pct=outputs.funding.preHandoverPct,
        handover_pct=outputs.funding.handoverPct,
        presale_threshold_pct=round(assumptions.presaleThresholdPct),
        presales_at_construction_start_aed=round(
            outputs.program.grossRevenueAed * (outputs.funding.depositPct / 100)
        ),
        escrow_retention_pct=round(assumptions.escrowRetentionPct),
        debt_to_cost_ratio=round(assumptions.debtToCostRatio, 4),
        debt_repayment_mode=assumptions.debtRepaymentMode,
        off_plan_proceeds_aed=outputs.funding.offPlanProceedsAed,
        debt_funding_aed=outputs.funding.debtFundingAed,
        equity_funding_aed=outputs.funding.equityFundingAed,
        vat_refunds_aed=outputs.funding.vatRefundsAed,
        total_sources_aed=outputs.funding.totalSourcesAed,
        total_uses_aed=outputs.funding.totalUsesAed,
        funding_gap_aed=outputs.funding.gapAed,
        sources=[
            FeasibilityFundingSource(
                code=row.code, label=row.label, amount_aed=row.amountAed, basis=row.basis
            )
            for row in outputs.sourcesUses.sources
        ],
    )

    salesStart = parseIsoDate(
        assumptions.salesCommencementDate, datetime(2026, 6, 1, tzinfo=timezone.utc)
    )
    constructionStart = parseIsoDate(
        assumptions.constructionDate, datetime(2026, 7, 1, tzinfo=timezone.utc)
    )
    handoverDate = parseIsoDate(assumptions.handoverDate, datetime(2029, 1, 1, tzinfo=timezone.utc))
    schedule = FeasibilityScheduleSummary(
        sales_commencement_date=assumptions.salesCommencementDate,
        construction_start_date=assumptions.constructionDate,
        handover_date=assumptions.handoverDate,
        sales_period_months=max(int(round(assumptions.salesPeriodMonths)), 1),
        construction_duration_months=max(_months_between(constructionStart, handoverDate), 1),
        sales_to_handover_months=max(_months_between(salesStart, handoverDate), 1),
    )

    cash_flow = FeasibilityCashFlowSummary(
        periods=[
            FeasibilityCashFlowPeriod(
                period_label=period.periodLabel,
                period_end_date=period.periodEndDate,
                revenue_inflows_aed=period.revenueInflowsAed,
                operating_outflows_aed=period.operatingOutflowsAed,
                debt_draw_aed=period.debtDrawAed,
                debt_repayment_aed=period.debtRepaymentAed,
                interest_paid_aed=period.interestPaidAed,
                commitment_fee_paid_aed=period.commitmentFeePaidAed,
                equity_contribution_aed=period.equityContributionAed,
                equity_distribution_aed=period.equityDistributionAed,
                debt_balance_aed=period.debtBalanceAed,
                debt_headroom_aed=period.debtHeadroomAed,
                escrow_balance_aed=period.escrowBalanceAed,
                unlevered_net_cash_flow_aed=period.unleveredNetCashFlowAed,
                levered_net_cash_flow_aed=period.leveredNetCashFlowAed,
                deposit_inflows_aed=period.depositInflowsAed,
                pre_handover_inflows_aed=period.preHandoverInflowsAed,
                handover_inflows_aed=period.handoverInflowsAed,
                land_loan_balance_aed=period.landLoanBalanceAed,
                construction_loan_balance_aed=period.constructionLoanBalanceAed,
                cost_land_aed=period.costLandAed,
                cost_construction_aed=period.costConstructionAed,
                cost_marketing_aed=period.costMarketingAed,
                cost_sales_agent_aed=period.costSalesAgentAed,
                cost_contingency_aed=period.costContingencyAed,
                cost_vat_aed=period.costVatAed,
                land_draw_aed=period.landDrawAed,
                construction_draw_aed=period.constructionDrawAed,
                vat_refund_inflows_aed=period.vatRefundInflowsAed,
            )
            for period in outputs.cashFlow.periods
        ]
    )

    returns = FeasibilityReturnsSummary(
        project_profit_aed=outputs.returns.grossProfitAed,
        gross_margin_pct=outputs.returns.grossMarginPct,
        all_in_project_profit_aed=outputs.returns.allInProjectProfitAed,
        all_in_margin_pct=outputs.returns.allInMarginPct,
        project_irr_pct=outputs.returns.projectIrrPct,
        project_moic=outputs.returns.projectMoic,
        equity_irr_pct=outputs.returns.equityIrrPct,
        equity_moic=outputs.returns.equityMoic,
        peak_debt_aed=outputs.returns.peakDebtAed,
        peak_equity_aed=outputs.returns.peakEquityAed,
        total_interest_paid_aed=outputs.returns.totalInterestPaidAed,
        total_commitment_fees_aed=outputs.returns.totalCommitmentFeesAed,
    )

    financing = FeasibilityFinancingSummary(
        base_project_cost_aed=outputs.financing.baseProjectCostAed,
        all_in_project_cost_aed=outputs.financing.allInProjectCostAed,
        all_in_cost_to_revenue_pct=outputs.financing.allInCostToRevenuePct,
        presale_coverage_pct_at_construction=outputs.financing.presaleCoveragePctAtConstruction,
        required_completion_reserve_aed=outputs.financing.requiredCompletionReserveAed,
        completion_reserve_coverage_pct=outputs.financing.completionReserveCoveragePct,
        sponsor_release_capacity_aed=outputs.financing.sponsorReleaseCapacityAed,
        debt_commitment_utilization_pct=outputs.financing.debtCommitmentUtilizationPct,
        debt_commitment_aed=outputs.financing.debtCommitmentAed,
        peak_debt_aed=outputs.financing.peakDebtAed,
        min_debt_headroom_aed=outputs.financing.minDebtHeadroomAed,
        arrangement_fee_aed=outputs.financing.arrangementFeeAed,
        initial_commitment_fee_aed=outputs.financing.initialCommitmentFeeAed,
        capitalized_interest_aed=outputs.financing.capitalizedInterestAed,
        commitment_fee_carry_aed=outputs.financing.commitmentFeeCarryAed,
        total_finance_costs_aed=outputs.financing.totalFinanceCostsAed,
        equity_contributed_aed=outputs.financing.equityContributedAed,
        equity_distributed_aed=outputs.financing.equityDistributedAed,
        closing_debt_balance_aed=outputs.financing.closingDebtBalanceAed,
        closing_escrow_balance_aed=outputs.financing.closingEscrowBalanceAed,
    )

    return FeasibilityWorkbook(
        generated_at=datetime.now(timezone.utc),
        plot_number=plot.plot_number,
        site=site,
        program=program,
        costs=costs,
        funding=funding,
        schedule=schedule,
        cash_flow=cash_flow,
        returns=returns,
        financing=financing,
        validation=validation,
    )


def compute_feasibility_summary(workbook: FeasibilityWorkbook) -> FeasibilityComputedSummary:
    return FeasibilityComputedSummary(
        plot_number=workbook.plot_number,
        usage=workbook.site.permitted_use,
        market_area=workbook.program.market_area,
        headline=workbook.program.headline,
        total_units=workbook.program.total_units,
        total_saleable_area_sqm=workbook.program.saleable_area_sqm,
        total_parking_spaces=workbook.program.total_parking_spaces,
        modeled_gfa_sqm=workbook.site.modeled_gfa_sqm or workbook.site.max_gfa_sqm,
        gross_saleable_area_sqm=workbook.site.gross_saleable_area_sqm,
        gsa_as_pct_of_gfa=round(
            (workbook.program.saleable_area_sqm / workbook.site.max_gfa_sqm) * 100
        )
        if workbook.site.max_gfa_sqm > 0
        else None,
        weighted_avg_sales_rate_aed_per_sqm=workbook.program.weighted_avg_sales_rate_aed_per_sqm,
        gross_revenue_aed=workbook.program.gross_revenue_aed,
        total_costs_incl_vat_aed=workbook.costs.total_costs_incl_vat_aed,
        gross_profit_aed=workbook.costs.gross_profit_aed,
        gross_margin_pct=workbook.costs.gross_margin_pct,
        off_plan_proceeds_aed=workbook.funding.off_plan_proceeds_aed,
        debt_funding_aed=workbook.funding.debt_funding_aed,
        equity_funding_aed=workbook.funding.equity_funding_aed,
        funding_gap_aed=workbook.funding.funding_gap_aed,
        project_irr_pct=workbook.returns.project_irr_pct,
        equity_irr_pct=workbook.returns.equity_irr_pct,
        project_moic=workbook.returns.project_moic,
        equity_moic=workbook.returns.equity_moic,
        peak_debt_aed=workbook.returns.peak_debt_aed,
        total_interest_paid_aed=workbook.returns.total_interest_paid_aed,
        total_commitment_fees_aed=workbook.returns.total_commitment_fees_aed,
        validation=workbook.validation,
        warnings=[*workbook.site.warnings, *workbook.program.warnings],
    )


def _months_between(start: datetime, end: datetime) -> int:
    return max((end.year - start.year) * 12 + (end.month - start.month), 0)


def _can_parse_iso_date(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return True


def _is_finite(value: float) -> bool:
    return value not in {float("inf"), float("-inf")} and value == value


__all__ = [
    "computeWorkbook",
    "compute_feasibility_summary",
    "compute_feasibility_workbook",
    "validateWorkbook",
]
