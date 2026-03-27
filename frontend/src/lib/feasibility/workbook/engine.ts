// ══════════════════════════════════════════════════════════════════════════════
// Workbook Engine — Clean implementation
// ══════════════════════════════════════════════════════════════════════════════
// Core contract: computeWorkbook(assumptions) → outputs
// All calculations derive from assumptions. No external dependencies.
// ══════════════════════════════════════════════════════════════════════════════

import type { FeasibilityAssumptions, UsageType } from './models'

// ── Output Types ─────────────────────────────────────────────────────────────

export interface AreaOutputs {
	plotAreaSqm: number
	maxGfaSqm: number
	maxStoreys: number | null
	appliedCoveragePct: number
	buildableFootprintSqm: number
	builtUpAreaSqm: number
	modeledGfaSqm: number
	grossSaleableAreaSqm: number
	parkingBuaAllowanceSqm: number
	totalBuaSqm: number
	notes: string[]
}

export interface ProgramRow {
	id: string
	label: string
	units: number
	avgSizeSqm: number
	totalAreaSqm: number
	sellingRatePsqm: number
	revenueAed: number
	parkingSpaces: number
}

export interface ProgramOutputs {
	rows: ProgramRow[]
	totalUnits: number
	totalAreaSqm: number
	totalParkingSpaces: number
	grossRevenueAed: number
	weightedAvgSalesRatePsqm: number
}

export interface CostOutputs {
	landAcquisitionAed: number
	landTransferFeeAed: number
	brokerageFeeAed: number
	legalDdCostAed: number
	totalLandCostAed: number

	constructionCostAed: number
	inflationCostAed: number
	constructionCostInclInflationAed: number

	designSupervisionCostAed: number
	marketingCostAed: number
	salesAgentFeesAed: number
	infrastructureCostAed: number
	governmentFeesAed: number
	masterCommunityFeesAed: number
	ffeOsePreopeningCostAed: number
	contingencyCostAed: number
	demolitionCostAed: number

	totalCostsExclVatAed: number
	vatAmountAed: number
	totalCostsInclVatAed: number
}

export interface FundingOutputs {
	depositPct: number
	preHandoverPct: number
	handoverPct: number

	offPlanProceedsAed: number
	debtFundingAed: number
	equityFundingAed: number
	vatRefundsAed: number
	totalSourcesAed: number

	totalUsesAed: number
	gapAed: number

	landLoanCapacityAed: number
	constructionLoanCapacityAed: number
	totalDebtCapacityAed: number

	// Effective rates
	landLoanRatePct: number
	constructionLoanRatePct: number
}

export interface CashFlowPeriod {
	periodLabel: string
	periodEndDate: string
	revenueInflowsAed: number
	depositInflowsAed: number
	preHandoverInflowsAed: number
	handoverInflowsAed: number
	vatRefundInflowsAed: number
	operatingOutflowsAed: number
	costLandAed: number
	costConstructionAed: number
	costProfessionalFeesAed: number
	costMarketingAed: number
	costSalesAgentAed: number
	costInfrastructureAed: number
	costAuthorityFeesAed: number
	costCommunityFeesAed: number
	costContingencyAed: number
	costVatAed: number
	unleveredNetCashFlowAed: number
	debtDrawAed: number
	debtRepaymentAed: number
	interestPaidAed: number
	commitmentFeePaidAed: number
	equityContributionAed: number
	equityDistributionAed: number
	leveredNetCashFlowAed: number
	debtBalanceAed: number
	debtHeadroomAed: number
	landLoanBalanceAed: number
	constructionLoanBalanceAed: number
	costPaidFromEscrowAed: number
	escrowBalanceAed: number
	landDrawAed: number
	constructionDrawAed: number
}

export interface CashFlowOutputs {
	periods: CashFlowPeriod[]
	totalRevenueAed: number
	totalCostsAed: number
	peakFundingAed: number
}

export interface ReturnsOutputs {
	grossProfitAed: number
	grossMarginPct: number
	allInProjectCostAed: number
	allInProjectProfitAed: number
	allInMarginPct: number
	projectIrrPct: number | null
	projectMoic: number
	equityIrrPct: number | null
	equityMoic: number
	totalInterestPaidAed: number
	totalCommitmentFeesAed: number
	arrangementFeeAed: number
	peakDebtAed: number
	peakEquityAed: number
}

export interface FinancingOutputs {
	baseProjectCostAed: number
	allInProjectCostAed: number
	allInCostToRevenuePct: number
	presaleCoveragePctAtConstruction: number
	requiredCompletionReserveAed: number
	completionReserveCoveragePct: number
	sponsorReleaseCapacityAed: number
	debtCommitmentUtilizationPct: number
	debtCommitmentAed: number
	peakDebtAed: number
	minDebtHeadroomAed: number
	arrangementFeeAed: number
	initialCommitmentFeeAed: number
	capitalizedInterestAed: number
	commitmentFeeCarryAed: number
	totalFinanceCostsAed: number
	equityContributedAed: number
	equityDistributedAed: number
	closingDebtBalanceAed: number
	closingEscrowBalanceAed: number
}

export interface BudgetTimingPeriod {
	periodLabel: string
	periodEndDate: string
	budgetedCostsAed: number
	sellingCostsAed: number
	constructionRelatedCostsAed: number
	vatCostsAed: number
}

export interface BudgetTimingOutputs {
	periods: BudgetTimingPeriod[]
	totalBudgetedCostsAed: number
}

export interface SourcesUsesRow {
	category: 'source' | 'use'
	code: string
	label: string
	amountAed: number
	basis: string
}

export interface SourcesUsesOutputs {
	sources: SourcesUsesRow[]
	uses: SourcesUsesRow[]
	totalSourcesAed: number
	totalUsesAed: number
	gapAed: number
}

export interface WorkbookOutputs {
	area: AreaOutputs
	program: ProgramOutputs
	costs: CostOutputs
	funding: FundingOutputs
	cashFlow: CashFlowOutputs
	returns: ReturnsOutputs
	financing: FinancingOutputs
	budgetTiming: BudgetTimingOutputs
	sourcesUses: SourcesUsesOutputs
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function round(value: number, digits = 2): number {
	const factor = 10 ** digits
	return Math.round(value * factor) / factor
}

function parseIsoDate(s: string, fallback: Date): Date {
	const parsed = new Date(s)
	return Number.isNaN(parsed.getTime()) ? fallback : parsed
}

function addMonths(dt: Date, months: number): Date {
	return new Date(Date.UTC(dt.getUTCFullYear(), dt.getUTCMonth() + months, 1))
}

function endOfMonth(d: Date): Date {
	return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0))
}

function iterMonthEnds(start: Date, end: Date): Date[] {
	let cursor = endOfMonth(start)
	const periods: Date[] = []
	while (cursor < end) {
		periods.push(cursor)
		cursor = endOfMonth(addMonths(cursor, 1))
	}
	periods.push(endOfMonth(end))
	return periods.filter((m, i) => i === 0 || m.getTime() !== periods[i - 1].getTime())
}

function periodicIrr(cashFlows: number[], periodsPerYear: number): number | null {
	if (!cashFlows.some((cf) => cf > 0) || !cashFlows.some((cf) => cf < 0)) return null
	const npv = (rate: number) => cashFlows.reduce((sum, cf, idx) => sum + cf / (1 + rate) ** idx, 0)
	let rate = 0.05
	const minRate = -0.9999
	const maxRate = 5.0
	let newtonConverged = false
	for (let i = 0; i < 100; i++) {
		const n = npv(rate)
		const dn = cashFlows.reduce((sum, cf, idx) => sum - (idx * cf) / (1 + rate) ** (idx + 1), 0)
		if (!Number.isFinite(n) || !Number.isFinite(dn)) break
		if (Math.abs(dn) < 1e-10) break
		let nextRate = rate - n / dn
		if (!Number.isFinite(nextRate)) break
		nextRate = Math.max(Math.min(nextRate, maxRate), minRate)
		if (Math.abs(nextRate - rate) < 1e-7) {
			rate = nextRate
			newtonConverged = true
			break
		}
		rate = nextRate
	}
	if (newtonConverged && rate > minRate && rate < maxRate && Number.isFinite(rate)) {
		const annualised = ((1 + rate) ** periodsPerYear - 1) * 100
		if (Number.isFinite(annualised)) return annualised
	}
	let lo = -0.999
	let hi = 5.0
	let npvLo = npv(lo)
	let npvHi = npv(hi)
	if (!Number.isFinite(npvLo) || !Number.isFinite(npvHi)) return null
	if (npvLo * npvHi > 0) return null
	for (let i = 0; i < 200; i++) {
		const mid = (lo + hi) / 2
		const npvMid = npv(mid)
		if (Math.abs(npvMid) < 1e-2 || hi - lo < 1e-8) {
			rate = mid
			break
		}
		if (npvLo * npvMid < 0) {
			hi = mid
			npvHi = npvMid
		} else {
			lo = mid
			npvLo = npvMid
		}
	}
	const annualised = ((1 + rate) ** periodsPerYear - 1) * 100
	return Number.isFinite(annualised) ? annualised : null
}

type PeriodRevenue = { deposit: number; preHandover: number; handover: number }

function scurveWeights(n: number): number[] {
	if (n <= 1) return [1.0]
	const k = 8.0 / Math.max(n, 1)
	const mid = (n - 1) / 2.0
	const raw = Array.from({ length: n }, (_, i) => {
		const x = Math.exp(k * (i - mid))
		return x / (1 + x) ** 2
	})
	const total = raw.reduce((s, v) => s + v, 0) || 1.0
	return raw.map((w) => w / total)
}

function revenueByPeriod(
	monthEnds: Date[],
	salesStart: Date,
	handover: Date,
	salesPeriodMonths: number,
	depositRevenue: number,
	preHandoverRevenue: number,
	handoverRevenue: number,
	milestoneDate: Date | null
): Map<string, PeriodRevenue> {
	const key = (d: Date) => d.toISOString().slice(0, 10)
	const result = new Map<string, PeriodRevenue>(
		monthEnds.map((m) => [key(m), { deposit: 0, preHandover: 0, handover: 0 }])
	)
	const salesStartMe = endOfMonth(salesStart)
	const salesEndMe = endOfMonth(addMonths(salesStart, salesPeriodMonths - 1))
	let salesMonths = monthEnds.filter(
		(m) => m.getTime() >= salesStartMe.getTime() && m.getTime() <= salesEndMe.getTime()
	)
	if (salesMonths.length === 0) salesMonths = monthEnds.length > 0 ? [salesStartMe] : []
	const weights = scurveWeights(salesMonths.length)
	const handoverMe = endOfMonth(handover)
	const handoverKey = key(handoverMe)
	const lastPreHandoverMe = endOfMonth(addMonths(handover, -1))
	let milestoneMe: Date | null = null
	if (milestoneDate !== null) {
		const candidate = endOfMonth(milestoneDate)
		if (
			candidate.getTime() > salesStartMe.getTime() &&
			candidate.getTime() < handoverMe.getTime() &&
			result.has(key(candidate))
		) {
			milestoneMe = candidate
		}
	}
	function addRev(periodEnd: Date, deposit = 0, preHandover = 0, handover = 0) {
		const k = key(periodEnd)
		const prev = result.get(k)
		if (!prev) return
		result.set(k, {
			deposit: round(prev.deposit + deposit),
			preHandover: round(prev.preHandover + preHandover),
			handover: round(prev.handover + handover)
		})
	}
	function allocateEvenly(
		periods: Date[],
		amount: number,
		field: 'deposit' | 'preHandover' | 'handover'
	) {
		if (amount <= 0 || periods.length === 0) return
		const perPeriod = round(amount / periods.length)
		let running = 0
		for (let i = 0; i < periods.length; i++) {
			const allocated = i < periods.length - 1 ? perPeriod : round(amount - running)
			running = round(running + allocated)
			if (field === 'deposit') addRev(periods[i], allocated, 0, 0)
			else if (field === 'preHandover') addRev(periods[i], 0, allocated, 0)
			else addRev(periods[i], 0, 0, allocated)
		}
	}
	for (let idx = 0; idx < salesMonths.length; idx++) {
		const salePeriodEnd = salesMonths[idx]
		const w = weights[idx]
		const cohortDeposit = round(depositRevenue * w)
		const cohortPreHandover = round(preHandoverRevenue * w)
		const cohortHandover = round(handoverRevenue * w)
		addRev(salePeriodEnd, cohortDeposit, 0, 0)
		if (cohortPreHandover > 0 && salePeriodEnd.getTime() < handoverMe.getTime()) {
			if (milestoneMe !== null) {
				let cp = salePeriodEnd.getTime() <= milestoneMe.getTime() ? milestoneMe : salePeriodEnd
				if (cp.getTime() > lastPreHandoverMe.getTime()) cp = lastPreHandoverMe
				addRev(cp, 0, cohortPreHandover, 0)
			} else {
				const collectionPeriods = monthEnds.filter(
					(m) => m.getTime() > salePeriodEnd.getTime() && m.getTime() < handoverMe.getTime()
				)
				if (collectionPeriods.length === 0) {
					addRev(salePeriodEnd, 0, cohortPreHandover, 0)
				} else {
					allocateEvenly(collectionPeriods, cohortPreHandover, 'preHandover')
				}
			}
		}
		addRev(handoverMe, 0, 0, cohortHandover)
	}
	let totDep = 0,
		totPH = 0,
		totHO = 0
	for (const v of result.values()) {
		totDep += v.deposit
		totPH += v.preHandover
		totHO += v.handover
	}
	const dDep = round(depositRevenue - totDep)
	const dPH = round(preHandoverRevenue - totPH)
	const dHO = round(handoverRevenue - totHO)
	if (result.has(handoverKey) && (dDep || dPH || dHO)) {
		const prev = result.get(handoverKey)
		if (!prev) return result
		result.set(handoverKey, {
			deposit: round(prev.deposit + dDep),
			preHandover: round(prev.preHandover + dPH),
			handover: round(prev.handover + dHO)
		})
	}
	return result
}

// ── Area Chain Benchmarks ────────────────────────────────────────────────────

type BuildingForm = 'low_rise' | 'mid_rise' | 'tower'

interface RatioBand {
	low: number
	base: number
	high: number
}

interface AreaBenchmark {
	usage: 'residential' | 'commercial' | 'mixed_use'
	buildingForm: BuildingForm
	coverageRatio: RatioBand
	buaToGfaEfficiency: RatioBand
	gfaToGsaEfficiency: RatioBand
}

const AREA_BENCHMARKS: AreaBenchmark[] = [
	{
		usage: 'residential',
		buildingForm: 'low_rise',
		coverageRatio: { low: 0.55, base: 0.6, high: 0.65 },
		buaToGfaEfficiency: { low: 0.89, base: 0.91, high: 0.93 },
		gfaToGsaEfficiency: { low: 0.8, base: 0.84, high: 0.87 }
	},
	{
		usage: 'residential',
		buildingForm: 'mid_rise',
		coverageRatio: { low: 0.4, base: 0.45, high: 0.5 },
		buaToGfaEfficiency: { low: 0.85, base: 0.88, high: 0.9 },
		gfaToGsaEfficiency: { low: 0.76, base: 0.8, high: 0.83 }
	},
	{
		usage: 'residential',
		buildingForm: 'tower',
		coverageRatio: { low: 0.35, base: 0.38, high: 0.4 },
		buaToGfaEfficiency: { low: 0.83, base: 0.86, high: 0.88 },
		gfaToGsaEfficiency: { low: 0.73, base: 0.77, high: 0.8 }
	},
	{
		usage: 'mixed_use',
		buildingForm: 'mid_rise',
		coverageRatio: { low: 0.4, base: 0.44, high: 0.5 },
		buaToGfaEfficiency: { low: 0.85, base: 0.88, high: 0.9 },
		gfaToGsaEfficiency: { low: 0.75, base: 0.78, high: 0.81 }
	},
	{
		usage: 'commercial',
		buildingForm: 'mid_rise',
		coverageRatio: { low: 0.35, base: 0.42, high: 0.45 },
		buaToGfaEfficiency: { low: 0.84, base: 0.87, high: 0.89 },
		gfaToGsaEfficiency: { low: 0.7, base: 0.74, high: 0.77 }
	}
]

function classifyBuildingForm(maxStoreys: number | null): BuildingForm {
	const storeys = maxStoreys ?? 12
	if (storeys <= 8) return 'low_rise'
	if (storeys <= 20) return 'mid_rise'
	return 'tower'
}

function getBenchmark(usage: UsageType, maxStoreys: number | null): AreaBenchmark {
	const normalizedUsage: AreaBenchmark['usage'] =
		usage === 'commercial' || usage === 'mixed_use' || usage === 'residential'
			? usage
			: 'residential'
	const buildingForm = classifyBuildingForm(maxStoreys)
	return (
		AREA_BENCHMARKS.find((b) => b.usage === normalizedUsage && b.buildingForm === buildingForm) ??
		AREA_BENCHMARKS[0]
	)
}

// ── Calculation Modules ──────────────────────────────────────────────────────

function computeArea(a: FeasibilityAssumptions): AreaOutputs {
	const benchmark = getBenchmark(a.usage, a.maxStoreys)

	const appliedCoveragePct = Math.min(
		a.maxCoveragePct ?? benchmark.coverageRatio.base * 100,
		benchmark.coverageRatio.base * 100
	)

	const buildableFootprintSqm = round(a.plotAreaSqm * (appliedCoveragePct / 100))

	const storeysFromGfa =
		buildableFootprintSqm > 0 && a.maxGfaSqm > 0
			? Math.max(Math.floor(a.maxGfaSqm / buildableFootprintSqm), 1)
			: (a.maxStoreys ?? 1)

	const derivedStoreys = Math.min(a.maxStoreys ?? storeysFromGfa, storeysFromGfa)
	const builtUpAreaSqm = round(buildableFootprintSqm * Math.max(derivedStoreys, 1))

	const modeledGfaSqm = round(
		Math.min(
			a.maxGfaSqm > 0 ? a.maxGfaSqm : builtUpAreaSqm * benchmark.buaToGfaEfficiency.base,
			builtUpAreaSqm * benchmark.buaToGfaEfficiency.base
		)
	)

	const grossSaleableAreaSqm = round(modeledGfaSqm * benchmark.gfaToGsaEfficiency.base)

	const totalParkingSpaces = a.unitConfigs.reduce(
		(sum, row) => sum + row.units * row.parkingRatio,
		0
	)
	const parkingBuaAllowanceSqm = round(totalParkingSpaces * 32.515)

	const totalBuaSqm = round(modeledGfaSqm * a.buaMultiplier + parkingBuaAllowanceSqm)

	const notes: string[] = []
	if (a.maxCoveragePct !== null) {
		notes.push(
			`Applied footprint ratio capped by GIS max coverage of ${round(a.maxCoveragePct, 1)}%.`
		)
	} else {
		notes.push('GIS max coverage missing, benchmark footprint ratios applied.')
	}

	return {
		plotAreaSqm: a.plotAreaSqm,
		maxGfaSqm: a.maxGfaSqm,
		maxStoreys: a.maxStoreys,
		appliedCoveragePct: round(appliedCoveragePct),
		buildableFootprintSqm,
		builtUpAreaSqm,
		modeledGfaSqm,
		grossSaleableAreaSqm,
		parkingBuaAllowanceSqm,
		totalBuaSqm,
		notes
	}
}

function computeProgram(a: FeasibilityAssumptions): ProgramOutputs {
	const rows: ProgramRow[] = a.unitConfigs
		.filter((row) => row.units > 0)
		.map((row) => ({
			id: row.id,
			label: row.label,
			units: row.units,
			avgSizeSqm: row.avgSizeSqm,
			totalAreaSqm: round(row.units * row.avgSizeSqm),
			sellingRatePsqm: row.sellingRatePsqm,
			revenueAed: round(row.units * row.avgSizeSqm * row.sellingRatePsqm),
			parkingSpaces: round(row.units * row.parkingRatio)
		}))

	const totalUnits = rows.reduce((sum, row) => sum + row.units, 0)
	const totalAreaSqm = rows.reduce((sum, row) => sum + row.totalAreaSqm, 0)
	const totalParkingSpaces = rows.reduce((sum, row) => sum + row.parkingSpaces, 0)
	const grossRevenueAed = rows.reduce((sum, row) => sum + row.revenueAed, 0)
	const weightedAvgSalesRatePsqm = totalAreaSqm > 0 ? round(grossRevenueAed / totalAreaSqm) : 0

	return {
		rows,
		totalUnits,
		totalAreaSqm,
		totalParkingSpaces,
		grossRevenueAed,
		weightedAvgSalesRatePsqm
	}
}

function computeCosts(
	a: FeasibilityAssumptions,
	area: AreaOutputs,
	program: ProgramOutputs
): CostOutputs {
	const landAcquisitionAed =
		a.landAcquisitionCostOverrideAed ?? round(a.plotAreaSqm * a.landPricePsqm)
	const landTransferFeeAed = round(landAcquisitionAed * 0.04)
	const totalLandCostAed = round(
		landAcquisitionAed + landTransferFeeAed + a.brokerageFeeAed + a.legalDdCostAed
	)

	const constructionCostAed = round(area.totalBuaSqm * a.constructionCostPsqmBua)
	const inflationCostAed = round(constructionCostAed * (a.midPointInflationPct / 100))
	const constructionCostInclInflationAed =
		a.constructionCostOverrideAed ?? round(constructionCostAed + inflationCostAed)

	const designSupervisionCostAed =
		a.designSupervisionCostOverrideAed ??
		round(constructionCostAed * (a.designSupervisionPct / 100))

	const marketingCostAed =
		a.marketingCostOverrideAed ?? round(program.grossRevenueAed * (a.marketingCostPct / 100))
	const salesAgentFeesAed =
		a.salesAgentFeesOverrideAed ?? round(program.grossRevenueAed * (a.salesAgentFeePct / 100))

	const contingencyCostAed =
		a.contingencyCostOverrideAed ?? round(constructionCostAed * (a.contingencyPct / 100))
	const demolitionCostAed = a.demolitionEnabled ? a.demolitionCostAed : 0

	const totalCostsExclVatAed = round(
		totalLandCostAed +
			constructionCostInclInflationAed +
			designSupervisionCostAed +
			marketingCostAed +
			salesAgentFeesAed +
			a.infrastructureCostAed +
			a.governmentFeesAed +
			a.masterCommunityFeesAed +
			a.ffeOsePreopeningCostAed +
			contingencyCostAed +
			demolitionCostAed
	)

	const vatAmountAed = round(totalCostsExclVatAed * (a.vatPct / 100))
	const totalCostsInclVatAed = round(totalCostsExclVatAed + vatAmountAed)

	return {
		landAcquisitionAed,
		landTransferFeeAed,
		brokerageFeeAed: a.brokerageFeeAed,
		legalDdCostAed: a.legalDdCostAed,
		totalLandCostAed,
		constructionCostAed,
		inflationCostAed,
		constructionCostInclInflationAed,
		designSupervisionCostAed,
		marketingCostAed,
		salesAgentFeesAed,
		infrastructureCostAed: a.infrastructureCostAed,
		governmentFeesAed: a.governmentFeesAed,
		masterCommunityFeesAed: a.masterCommunityFeesAed,
		ffeOsePreopeningCostAed: a.ffeOsePreopeningCostAed,
		contingencyCostAed,
		demolitionCostAed,
		totalCostsExclVatAed,
		vatAmountAed,
		totalCostsInclVatAed
	}
}

function computeFunding(
	a: FeasibilityAssumptions,
	program: ProgramOutputs,
	costs: CostOutputs
): FundingOutputs {
	const depositPct = a.paymentPlan.depositPct
	const preHandoverPct = a.paymentPlan.constructionPct
	const handoverPct = a.paymentPlan.handoverPct

	const offPlanProceedsAed = round(program.grossRevenueAed * ((depositPct + preHandoverPct) / 100))

	const totalDebtCapacityAed = round(costs.totalCostsInclVatAed * a.debtToCostRatio)
	const landLoanCapacityAed = round(
		Math.min(costs.landAcquisitionAed * (a.landLoanLtvPct / 100), totalDebtCapacityAed)
	)
	const constructionLoanCapacityAed = round(Math.max(totalDebtCapacityAed - landLoanCapacityAed, 0))

	const debtFundingAed = a.debtFundingAed > 0 ? a.debtFundingAed : totalDebtCapacityAed
	const equityFundingAed =
		a.equityFundingAed > 0
			? a.equityFundingAed
			: round(Math.max(costs.totalCostsInclVatAed - debtFundingAed, 0))
	const vatRefundsAed = costs.vatAmountAed

	const totalSourcesAed = round(
		offPlanProceedsAed + debtFundingAed + equityFundingAed + vatRefundsAed
	)
	const totalUsesAed = costs.totalCostsInclVatAed
	const gapAed = round(totalUsesAed - totalSourcesAed)

	const landLoanRatePct = round(a.eiborRatePct + a.landLoanSpreadBps / 100, 2)
	const constructionLoanRatePct = round(a.eiborRatePct + a.constructionLoanSpreadBps / 100, 2)

	return {
		depositPct,
		preHandoverPct,
		handoverPct,
		offPlanProceedsAed,
		debtFundingAed,
		equityFundingAed,
		vatRefundsAed,
		totalSourcesAed,
		totalUsesAed,
		gapAed,
		landLoanCapacityAed,
		constructionLoanCapacityAed,
		totalDebtCapacityAed,
		landLoanRatePct,
		constructionLoanRatePct
	}
}

function computeCashFlow(
	a: FeasibilityAssumptions,
	costs: CostOutputs,
	funding: FundingOutputs,
	program: ProgramOutputs
): CashFlowOutputs {
	const salesStart = parseIsoDate(a.salesCommencementDate, new Date(Date.UTC(2026, 5, 1)))
	const constructionStartDate = parseIsoDate(a.constructionDate, new Date(Date.UTC(2026, 6, 1)))
	const handoverDate = parseIsoDate(a.handoverDate, new Date(Date.UTC(2029, 0, 1)))
	const landAcqDate = parseIsoDate(a.landAcquisitionDate, salesStart)
	const milestoneDateRaw = a.preHandoverMilestoneDate
	const milestoneDate: Date | null = milestoneDateRaw
		? (() => {
				const d = new Date(milestoneDateRaw)
				return Number.isNaN(d.getTime()) ? null : d
			})()
		: null

	const salesPeriodMonths = Math.max(Math.round(a.salesPeriodMonths), 1)

	const timelineStart = new Date(
		Math.min(landAcqDate.getTime(), salesStart.getTime(), constructionStartDate.getTime())
	)
	const monthEnds = iterMonthEnds(timelineStart, handoverDate)
	const landPeriodEnd = endOfMonth(landAcqDate)
	const handoverMe = endOfMonth(handoverDate)
	const constructionStartMe = endOfMonth(constructionStartDate)
	const constructionActivePeriods = monthEnds.filter(
		(m) => m.getTime() >= constructionStartMe.getTime() && m.getTime() < handoverMe.getTime()
	)
	const constructionActiveCount = Math.max(constructionActivePeriods.length, 1)

	const grossRevenue = program.grossRevenueAed
	const dep = round(grossRevenue * (funding.depositPct / 100))
	const preHandover = round(grossRevenue * (funding.preHandoverPct / 100))
	const handoverRev = round(grossRevenue * (funding.handoverPct / 100))

	const revenueMap = revenueByPeriod(
		monthEnds,
		salesStart,
		handoverDate,
		salesPeriodMonths,
		dep,
		preHandover,
		handoverRev,
		milestoneDate
	)

	const constructionPool =
		costs.constructionCostInclInflationAed +
		costs.designSupervisionCostAed +
		costs.infrastructureCostAed +
		costs.governmentFeesAed +
		costs.masterCommunityFeesAed +
		costs.ffeOsePreopeningCostAed +
		costs.demolitionCostAed

	const monthlyConstruction = round(constructionPool / constructionActiveCount)
	const monthlyMarketing = round(
		(costs.marketingCostAed + costs.salesAgentFeesAed) / Math.max(monthEnds.length, 1)
	)
	const monthlyContingency = round(costs.contingencyCostAed / constructionActiveCount)
	const monthlyVat = round(costs.vatAmountAed / constructionActiveCount)

	const annualRate = constructionLoanRatePctValue(a) / 100
	const monthlyRate = annualRate / 12
	const commitmentRate = a.commitmentFeePct / 100 / 12
	const debtLimit = funding.debtFundingAed

	const cashFlowPeriods: CashFlowPeriod[] = []
	let debtBalance = 0
	let escrowBalance = 0
	const lastPeriodEnd = monthEnds.at(-1) ?? handoverMe

	for (const periodEnd of monthEnds) {
		const rev = revenueMap.get(periodEnd.toISOString().slice(0, 10)) ?? {
			deposit: 0,
			preHandover: 0,
			handover: 0
		}
		const depositInflows = rev.deposit
		const preHandoverInflows = rev.preHandover
		const currentHandoverInflow = rev.handover
		const revenueInflows = round(depositInflows + preHandoverInflows + currentHandoverInflow)

		const constructionActive =
			periodEnd.getTime() >= constructionStartMe.getTime() &&
			periodEnd.getTime() < handoverMe.getTime()

		const costLand = periodEnd.getTime() === landPeriodEnd.getTime() ? costs.landAcquisitionAed : 0
		const costConstruction = constructionActive ? monthlyConstruction : 0
		const costContingency = constructionActive ? monthlyContingency : 0
		const costVat = constructionActive ? monthlyVat : 0

		const operatingOutflows = round(
			costLand + costConstruction + monthlyMarketing + costContingency + costVat
		)

		const isLast = periodEnd.getTime() === lastPeriodEnd.getTime()
		const vatRefundInflow = isLast ? costs.vatAmountAed : 0

		const cashBeforeDebt = escrowBalance + revenueInflows - operatingOutflows
		let debtDraw = 0
		if (cashBeforeDebt < 0) {
			debtDraw = Math.min(-cashBeforeDebt, Math.max(debtLimit - debtBalance, 0))
		}
		const commitmentFeePaid = round(Math.max(debtLimit - debtBalance, 0) * commitmentRate)
		const interestPaid = round(Math.max(debtBalance, 0) * monthlyRate)
		debtBalance = round(debtBalance + debtDraw + interestPaid + commitmentFeePaid)

		const cashAfterDebt = escrowBalance + revenueInflows + debtDraw - operatingOutflows
		let debtRepayment = 0
		if (isLast || a.debtRepaymentMode === 'sales_sweep') {
			debtRepayment = round(Math.min(Math.max(cashAfterDebt, 0), debtBalance))
			debtBalance = round(debtBalance - debtRepayment)
		}
		escrowBalance = round(cashAfterDebt - debtRepayment)

		let equityContribution = 0
		if (escrowBalance < 0) {
			equityContribution = round(-escrowBalance)
			escrowBalance = 0
		}

		let equityDistribution = 0
		if (isLast && escrowBalance > 0) {
			equityDistribution = round(Math.max(escrowBalance * (1 - a.escrowRetentionPct / 100), 0))
			escrowBalance = round(escrowBalance - equityDistribution)
		}

		cashFlowPeriods.push({
			periodLabel: periodEnd.toLocaleString('en-US', {
				month: 'short',
				year: 'numeric',
				timeZone: 'UTC'
			}),
			periodEndDate: periodEnd.toISOString().slice(0, 10),
			revenueInflowsAed: revenueInflows,
			depositInflowsAed: depositInflows,
			preHandoverInflowsAed: preHandoverInflows,
			handoverInflowsAed: currentHandoverInflow,
			vatRefundInflowsAed: vatRefundInflow,
			operatingOutflowsAed: operatingOutflows,
			costLandAed: costLand,
			costConstructionAed: costConstruction,
			costProfessionalFeesAed: 0,
			costMarketingAed: monthlyMarketing,
			costSalesAgentAed: 0,
			costInfrastructureAed: 0,
			costAuthorityFeesAed: 0,
			costCommunityFeesAed: 0,
			costContingencyAed: costContingency,
			costVatAed: costVat,
			unleveredNetCashFlowAed: round(revenueInflows + vatRefundInflow - operatingOutflows),
			debtDrawAed: round(debtDraw),
			debtRepaymentAed: debtRepayment,
			interestPaidAed: interestPaid,
			commitmentFeePaidAed: commitmentFeePaid,
			equityContributionAed: equityContribution,
			equityDistributionAed: equityDistribution,
			leveredNetCashFlowAed: round(
				revenueInflows -
					operatingOutflows +
					debtDraw -
					debtRepayment -
					equityContribution +
					equityDistribution
			),
			debtBalanceAed: round(debtBalance),
			debtHeadroomAed: round(Math.max(debtLimit - debtBalance, 0)),
			landLoanBalanceAed: round(Math.min(debtBalance, funding.debtFundingAed * 0.35)),
			constructionLoanBalanceAed: round(Math.max(debtBalance - funding.debtFundingAed * 0.35, 0)),
			costPaidFromEscrowAed: 0,
			escrowBalanceAed: escrowBalance,
			landDrawAed: round(Math.min(debtDraw, costLand)),
			constructionDrawAed: round(Math.max(debtDraw - costLand, 0))
		})
	}

	const totalRevenueAed = dep + preHandover + handoverRev
	const totalCostsAed = costs.totalCostsInclVatAed
	const peakFundingAed = Math.abs(Math.min(...cashFlowPeriods.map((p) => p.escrowBalanceAed), 0))

	return {
		periods: cashFlowPeriods,
		totalRevenueAed,
		totalCostsAed,
		peakFundingAed
	}
}

function constructionLoanRatePctValue(a: FeasibilityAssumptions): number {
	return a.eiborRatePct + a.constructionLoanSpreadBps / 100
}

function computeReturns(
	a: FeasibilityAssumptions,
	program: ProgramOutputs,
	costs: CostOutputs,
	funding: FundingOutputs,
	periods: CashFlowPeriod[]
): ReturnsOutputs {
	const projectCashflows = periods.map((p) => p.unleveredNetCashFlowAed)
	const equityCashflows = periods.map((p) => -p.equityContributionAed + p.equityDistributionAed)

	const projectIrrPct = periodicIrr(projectCashflows, 12)
	const equityIrrPct = periodicIrr(equityCashflows, 12)

	const totalInterestPaidAed = round(periods.reduce((sum, p) => sum + p.interestPaidAed, 0))
	const totalCommitmentFeesAed = round(periods.reduce((sum, p) => sum + p.commitmentFeePaidAed, 0))
	const arrangementFeeAed = round(funding.debtFundingAed * (a.arrangementFeePct / 100))

	const grossProfitAed = round(program.grossRevenueAed - costs.totalCostsInclVatAed)
	const grossMarginPct =
		program.grossRevenueAed > 0 ? round((grossProfitAed / program.grossRevenueAed) * 100) : 0

	const allInProjectCostAed = round(
		costs.totalCostsInclVatAed + totalInterestPaidAed + totalCommitmentFeesAed + arrangementFeeAed
	)
	const allInProjectProfitAed = round(program.grossRevenueAed - allInProjectCostAed)
	const allInMarginPct =
		program.grossRevenueAed > 0 ? round((allInProjectProfitAed / program.grossRevenueAed) * 100) : 0

	const projectMoic =
		costs.totalCostsInclVatAed > 0
			? round(program.grossRevenueAed / costs.totalCostsInclVatAed, 3)
			: 0

	const totalEquityContributed = round(periods.reduce((sum, p) => sum + p.equityContributionAed, 0))
	const totalEquityDistributed = round(periods.reduce((sum, p) => sum + p.equityDistributionAed, 0))
	const equityMoic =
		totalEquityContributed > 0 ? round(totalEquityDistributed / totalEquityContributed, 3) : 0

	const peakDebtAed = Math.max(...periods.map((p) => p.debtBalanceAed), 0)
	const peakEquityAed = Math.max(...periods.map((p) => p.equityContributionAed), 0)

	return {
		grossProfitAed,
		grossMarginPct,
		allInProjectCostAed,
		allInProjectProfitAed,
		allInMarginPct,
		projectIrrPct: projectIrrPct !== null ? round(projectIrrPct) : null,
		projectMoic,
		equityIrrPct: equityIrrPct !== null ? round(equityIrrPct) : null,
		equityMoic,
		totalInterestPaidAed,
		totalCommitmentFeesAed,
		arrangementFeeAed,
		peakDebtAed,
		peakEquityAed
	}
}

function computeFinancing(
	a: FeasibilityAssumptions,
	funding: FundingOutputs,
	costs: CostOutputs,
	program: ProgramOutputs,
	periods: CashFlowPeriod[]
): FinancingOutputs {
	const peakDebtAed = Math.max(...periods.map((p) => p.debtBalanceAed), 0)
	const minDebtHeadroomAed = periods.length
		? Math.min(...periods.map((p) => p.debtHeadroomAed))
		: funding.debtFundingAed
	const arrangementFeeAed = round(funding.debtFundingAed * (a.arrangementFeePct / 100))
	const initialCommitmentFeeAed = round(funding.debtFundingAed * (a.commitmentFeePct / 100))
	const capitalizedInterestAed = round(periods.reduce((sum, p) => sum + p.interestPaidAed, 0))
	const commitmentFeeCarryAed = round(periods.reduce((sum, p) => sum + p.commitmentFeePaidAed, 0))
	const totalFinanceCostsAed = round(
		arrangementFeeAed + initialCommitmentFeeAed + capitalizedInterestAed + commitmentFeeCarryAed
	)
	const finalPeriod = periods[periods.length - 1] ?? null
	const presalesAtConstructionStart = round(program.grossRevenueAed * (funding.depositPct / 100))

	return {
		baseProjectCostAed: costs.totalCostsInclVatAed,
		allInProjectCostAed: round(costs.totalCostsInclVatAed + totalFinanceCostsAed),
		allInCostToRevenuePct:
			program.grossRevenueAed > 0
				? round(
						((costs.totalCostsInclVatAed + totalFinanceCostsAed) / program.grossRevenueAed) * 100
					)
				: 0,
		presaleCoveragePctAtConstruction:
			program.grossRevenueAed > 0
				? round((presalesAtConstructionStart / program.grossRevenueAed) * 100)
				: 0,
		requiredCompletionReserveAed: round(program.grossRevenueAed * (a.escrowRetentionPct / 100)),
		completionReserveCoveragePct: round(
			((finalPeriod?.escrowBalanceAed ?? 0) /
				Math.max(program.grossRevenueAed * (a.escrowRetentionPct / 100), 1)) *
				100
		),
		sponsorReleaseCapacityAed: round(periods.reduce((sum, p) => sum + p.equityDistributionAed, 0)),
		debtCommitmentUtilizationPct:
			funding.debtFundingAed > 0 ? round((peakDebtAed / funding.debtFundingAed) * 100) : 0,
		debtCommitmentAed: funding.debtFundingAed,
		peakDebtAed,
		minDebtHeadroomAed,
		arrangementFeeAed,
		initialCommitmentFeeAed,
		capitalizedInterestAed,
		commitmentFeeCarryAed,
		totalFinanceCostsAed,
		equityContributedAed: round(periods.reduce((sum, p) => sum + p.equityContributionAed, 0)),
		equityDistributedAed: round(periods.reduce((sum, p) => sum + p.equityDistributionAed, 0)),
		closingDebtBalanceAed: finalPeriod?.debtBalanceAed ?? 0,
		closingEscrowBalanceAed: finalPeriod?.escrowBalanceAed ?? 0
	}
}

function computeBudgetTiming(periods: CashFlowPeriod[]): BudgetTimingOutputs {
	const budgetPeriods: BudgetTimingPeriod[] = periods.map((p) => ({
		periodLabel: p.periodLabel,
		periodEndDate: p.periodEndDate,
		budgetedCostsAed: round(p.operatingOutflowsAed),
		sellingCostsAed: round(p.costMarketingAed + p.costSalesAgentAed),
		constructionRelatedCostsAed: round(p.costConstructionAed + p.costContingencyAed),
		vatCostsAed: p.costVatAed
	}))
	return {
		periods: budgetPeriods,
		totalBudgetedCostsAed: round(periods.reduce((sum, p) => sum + p.operatingOutflowsAed, 0))
	}
}

function computeSourcesUses(funding: FundingOutputs, costs: CostOutputs): SourcesUsesOutputs {
	const sources: SourcesUsesRow[] = [
		{
			category: 'source',
			code: 'off_plan',
			label: 'Off-plan proceeds',
			amountAed: funding.offPlanProceedsAed,
			basis: 'deposit + pre-handover collections'
		},
		{
			category: 'source',
			code: 'debt',
			label: 'Senior debt',
			amountAed: funding.debtFundingAed,
			basis: 'debt-to-cost ratio'
		},
		{
			category: 'source',
			code: 'equity',
			label: 'Sponsor equity',
			amountAed: funding.equityFundingAed,
			basis: 'balancing source'
		},
		{
			category: 'source',
			code: 'vat_refund',
			label: 'VAT refunds',
			amountAed: funding.vatRefundsAed,
			basis: 'input tax recovery'
		}
	]

	const uses: SourcesUsesRow[] = [
		{
			category: 'use',
			code: 'land',
			label: 'Land acquisition',
			amountAed: costs.landAcquisitionAed,
			basis: 'plot area x land rate'
		},
		{
			category: 'use',
			code: 'construction',
			label: 'Construction',
			amountAed: costs.constructionCostInclInflationAed,
			basis: 'built-up area x construction rate'
		},
		{
			category: 'use',
			code: 'design',
			label: 'Design and supervision',
			amountAed: costs.designSupervisionCostAed,
			basis: '% of construction'
		},
		{
			category: 'use',
			code: 'marketing',
			label: 'Marketing',
			amountAed: costs.marketingCostAed,
			basis: '% of revenue'
		},
		{
			category: 'use',
			code: 'sales_agent',
			label: 'Sales agent fees',
			amountAed: costs.salesAgentFeesAed,
			basis: '% of revenue'
		},
		{
			category: 'use',
			code: 'infrastructure',
			label: 'Infrastructure',
			amountAed: costs.infrastructureCostAed,
			basis: 'input'
		},
		{
			category: 'use',
			code: 'authority',
			label: 'Authority fees',
			amountAed: costs.governmentFeesAed,
			basis: 'input'
		},
		{
			category: 'use',
			code: 'community',
			label: 'Master community fees',
			amountAed: costs.masterCommunityFeesAed,
			basis: 'input'
		},
		{
			category: 'use',
			code: 'contingency',
			label: 'Contingency',
			amountAed: costs.contingencyCostAed,
			basis: '% of non-land costs'
		},
		{
			category: 'use',
			code: 'vat',
			label: 'VAT',
			amountAed: costs.vatAmountAed,
			basis: '% of total costs'
		}
	]

	return {
		sources,
		uses,
		totalSourcesAed: funding.totalSourcesAed,
		totalUsesAed: costs.totalCostsInclVatAed,
		gapAed: round(costs.totalCostsInclVatAed - funding.totalSourcesAed)
	}
}

// ── Main Entry Point ─────────────────────────────────────────────────────────

export function computeWorkbook(assumptions: FeasibilityAssumptions): WorkbookOutputs {
	const area = computeArea(assumptions)
	const program = computeProgram(assumptions)
	const costs = computeCosts(assumptions, area, program)
	const funding = computeFunding(assumptions, program, costs)
	const cashFlow = computeCashFlow(assumptions, costs, funding, program)
	const financing = computeFinancing(assumptions, funding, costs, program, cashFlow.periods)
	const returns = computeReturns(assumptions, program, costs, funding, cashFlow.periods)
	const budgetTiming = computeBudgetTiming(cashFlow.periods)
	const sourcesUses = computeSourcesUses(funding, costs)

	return {
		area,
		program,
		costs,
		funding,
		cashFlow,
		returns,
		financing,
		budgetTiming,
		sourcesUses
	}
}
