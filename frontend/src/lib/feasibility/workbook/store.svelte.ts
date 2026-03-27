// ══════════════════════════════════════════════════════════════════════════════
// Workbook Store — workbook-first state management
// ══════════════════════════════════════════════════════════════════════════════
// Shape: { assumptions, context, research, outputs, validation }
// - assumptions: canonical mutable inputs
// - outputs: derived via engine.ts computeWorkbook(assumptions)
// - validation: derived via engine.ts validateWorkbook(assumptions, outputs)
// - context/research: secondary display data
// ══════════════════════════════════════════════════════════════════════════════

import type { PlotResearch, StudyContext } from '$lib/api/generated/hey-api/types.gen'
import {
	computeWorkbook as computeWorkbookOutputs,
	type WorkbookOutputs
} from '$lib/feasibility/workbook/engine'
import type {
	FeasibilityAssumptions,
	Plot,
	PlotDetails,
	UnitConfig
} from '$lib/feasibility/workbook/models'
import { type ValidationResult, validateWorkbook } from '$lib/feasibility/workbook/validation'

import { toSqft } from '$lib/utils/units'

// ── Types ────────────────────────────────────────────────────────────────────

export type WorkbookPhase = 'empty' | 'loading' | 'ready' | 'error'

export type ReviewDecisionType = 'accepted' | 'review_later' | 'needs_evidence'

export interface ReviewDecision {
	code: string
	decision: ReviewDecisionType
	timestamp: string
}

export type FeasibilitySheetTab =
	| 'key_assumptions'
	| 'sales_collections'
	| 'budget'
	| 'financing'
	| 'cashflow'
	| 'monthly_cf'
	| 'returns'
	| 'checks'
	| 'pricing_evidence'
	| 'eibor'

export interface WorkbookState {
	phase: WorkbookPhase
	plotData: PlotDetails | null
	assumptions: FeasibilityAssumptions | null
	study_context: StudyContext | null
	research: PlotResearch | null
	error: string | null
}

// ── Dirty tracking sets ──────────────────────────────────────────────────────

const UNIT_MIX_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'key_assumptions',
	'sales_collections',
	'budget',
	'financing',
	'cashflow',
	'monthly_cf',
	'returns',
	'checks'
]

const PAYMENT_PLAN_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'key_assumptions',
	'sales_collections',
	'financing',
	'cashflow',
	'monthly_cf',
	'returns',
	'checks'
]

const EIBOR_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'eiborRatePct',
	'landLoanSpreadBps',
	'constructionLoanSpreadBps'
])

const EIBOR_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'eibor',
	'financing',
	'cashflow',
	'monthly_cf',
	'returns',
	'checks'
]

const BUDGET_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'landPricePsqm',
	'landAcquisitionCostOverrideAed',
	'designSupervisionCostOverrideAed',
	'constructionCostOverrideAed',
	'demolitionCostAed',
	'infrastructureCostAed',
	'governmentFeesAed',
	'marketingCostOverrideAed',
	'salesAgentFeesOverrideAed',
	'masterCommunityFeesAed',
	'ffeOsePreopeningCostAed',
	'contingencyCostOverrideAed',
	'midPointInflationPct',
	'vatPct',
	'brokerageFeeAed',
	'legalDdCostAed',
	'constructionCostPsqmBua',
	'designSupervisionPct',
	'marketingCostPct',
	'salesAgentFeePct',
	'contingencyPct',
	'landAcquisitionDate',
	'demolitionEnablingDate',
	'constructionDate',
	'handoverDate'
])

const BUDGET_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'budget',
	'financing',
	'cashflow',
	'monthly_cf',
	'returns',
	'checks'
]

// ── Default Assumptions ──────────────────────────────────────────────────────

function todayIsoDate(): string {
	return new Date().toISOString().slice(0, 10)
}

function createDefaultAssumptions(): FeasibilityAssumptions {
	return {
		usage: 'unknown',
		plotAreaSqm: 0,
		maxGfaSqm: 0,
		maxCoveragePct: null,
		maxStoreys: null,
		maxFar: 0,
		buaMultiplier: 1,
		nsaEfficiencyPct: 80,
		numberOfTowers: 1,
		numberOfFloors: 1,
		unitConfigs: [],
		paymentPlan: { depositPct: 20, constructionPct: 40, handoverPct: 40 },
		standardParkingRatio: 1,
		largeUnitThresholdSqm: 140,
		largeUnitParkingRatio: 2,
		landPricePsqm: 0,
		landAcquisitionCostOverrideAed: null,
		brokerageFeeAed: 0,
		legalDdCostAed: 0,
		constructionCostPsqmBua: 0,
		constructionCostOverrideAed: null,
		midPointInflationPct: 0,
		designSupervisionPct: 0,
		designSupervisionCostOverrideAed: null,
		marketingCostPct: 0,
		marketingCostOverrideAed: null,
		salesAgentFeePct: 0,
		salesAgentFeesOverrideAed: null,
		infrastructureCostAed: 0,
		governmentFeesAed: 0,
		masterCommunityFeesAed: 0,
		ffeOsePreopeningCostAed: 0,
		contingencyPct: 0,
		contingencyCostOverrideAed: null,
		demolitionEnabled: false,
		demolitionCostAed: 0,
		vatPct: 5,
		debtToCostRatio: 0,
		landLoanLtvPct: 65,
		eiborRatePct: 4.85,
		landLoanSpreadBps: 365,
		constructionLoanSpreadBps: 465,
		arrangementFeePct: 1,
		commitmentFeePct: 0.5,
		presaleThresholdPct: 35,
		escrowRetentionPct: 5,
		debtRepaymentMode: 'bullet_at_handover',
		debtFundingAed: 0,
		equityFundingAed: 0,
		financeRatePct: 0,
		landAcquisitionDate: todayIsoDate(),
		demolitionEnablingDate: todayIsoDate(),
		salesCommencementDate: todayIsoDate(),
		salesPeriodMonths: 24,
		constructionDate: todayIsoDate(),
		handoverDate: todayIsoDate(),
		preHandoverMilestoneDate: todayIsoDate()
	}
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function parseMaxStoreys(maxHeight: string | null | undefined): number | null {
	if (!maxHeight) return null
	const matches = maxHeight.match(/(\d+)/g)
	if (!matches?.length) return null
	const storeys = Number(matches[matches.length - 1])
	return Number.isFinite(storeys) && storeys > 0 ? storeys : null
}

function parseMaxCoverage(maxCoverage: string | null | undefined): number | null {
	if (!maxCoverage) return null
	const match = maxCoverage.match(/(\d+(?:\.\d+)?)/)
	if (!match) return null
	const value = Number(match[1])
	return Number.isFinite(value) ? value : null
}

function seedAssumptionsFromPlot(plotData: PlotDetails): FeasibilityAssumptions {
	const base = createDefaultAssumptions()
	return {
		...base,
		usage: plotData.inferred_usage ?? 'unknown',
		plotAreaSqm: plotData.plot_area_sqm,
		maxGfaSqm: plotData.max_gfa_sqm ?? 0,
		maxCoveragePct: parseMaxCoverage(plotData.max_coverage),
		maxStoreys: parseMaxStoreys(plotData.max_height),
		maxFar: plotData.far ?? 0
	}
}

// ── Store ────────────────────────────────────────────────────────────────────

const state = $state<WorkbookState>({
	phase: 'empty',
	plotData: null,
	assumptions: null,
	study_context: null,
	research: null,
	error: null
})

const sheetDirty = $state<Record<FeasibilitySheetTab, boolean>>({
	key_assumptions: false,
	sales_collections: false,
	budget: false,
	financing: false,
	cashflow: false,
	monthly_cf: false,
	returns: false,
	checks: false,
	pricing_evidence: false,
	eibor: false
})

const activeSheet = $state<{ value: FeasibilitySheetTab }>({
	value: 'key_assumptions'
})

const reviewDecisions = $state<Record<string, ReviewDecision>>({})

const inputs = $derived<FeasibilityAssumptions>(state.assumptions ?? createDefaultAssumptions())

const outputs = $derived<WorkbookOutputs | null>(
	state.assumptions ? computeWorkbookOutputs(state.assumptions) : null
)

const validation = $derived<ValidationResult | null>(
	state.assumptions && outputs ? validateWorkbook(state.assumptions, outputs) : null
)

function markSheetsDirty(tabs: FeasibilitySheetTab[]): void {
	for (const tab of tabs) {
		sheetDirty[tab] = true
	}
}

function prelimParkingSpaces() {
	return (inputs.unitConfigs ?? [])
		.filter((row) => row.units > 0)
		.reduce((sum, row) => sum + row.units * row.parkingRatio, 0)
}

function maxGfaSqmValue() {
	if (inputs.maxGfaSqm > 0) return inputs.maxGfaSqm
	return inputs.plotAreaSqm * inputs.maxFar
}

function parkingBuaAllowanceSqm() {
	return prelimParkingSpaces() * 32.515
}

function totalBuaSqmValue() {
	if (outputs) return outputs.area.totalBuaSqm
	return maxGfaSqmValue() * inputs.buaMultiplier + parkingBuaAllowanceSqm()
}

function totalConfiguredAreaSqmValue() {
	return (inputs.unitConfigs ?? []).reduce((sum, row) => sum + row.units * row.avgSizeSqm, 0)
}

function totalConfiguredRevenueValue() {
	return (inputs.unitConfigs ?? []).reduce(
		(sum, row) => sum + row.units * row.avgSizeSqm * row.sellingRatePsqm,
		0
	)
}

function totalUnitsValue() {
	return (inputs.unitConfigs ?? []).reduce((sum, row) => sum + row.units, 0)
}

function totalParkingSpacesValue() {
	if (outputs) return outputs.program.totalParkingSpaces
	return (inputs.unitConfigs ?? []).reduce((sum, row) => sum + row.units * row.parkingRatio, 0)
}

function averageSellingPricePsqmValue() {
	if (outputs) return outputs.program.weightedAvgSalesRatePsqm
	const area = totalConfiguredAreaSqmValue()
	if (area <= 0) return 0
	return totalConfiguredRevenueValue() / area
}

function rawPlotAcquisitionCost() {
	return inputs.plotAreaSqm * inputs.landPricePsqm
}

function plotAcquisitionCostValue() {
	if (outputs) return outputs.costs.landAcquisitionAed
	return inputs.landAcquisitionCostOverrideAed ?? rawPlotAcquisitionCost()
}

function landTransferFeeAedValue() {
	if (outputs) return outputs.costs.landTransferFeeAed
	return plotAcquisitionCostValue() * 0.04
}

function totalLandCostAedValue() {
	if (outputs) return outputs.costs.totalLandCostAed
	return (
		plotAcquisitionCostValue() +
		landTransferFeeAedValue() +
		inputs.brokerageFeeAed +
		inputs.legalDdCostAed
	)
}

function constructionCostTotal() {
	return totalBuaSqmValue() * inputs.constructionCostPsqmBua
}

function inflationCostValue() {
	if (outputs) return outputs.costs.inflationCostAed
	return constructionCostTotal() * (inputs.midPointInflationPct / 100)
}

function rawConstructionCostInclInflation() {
	return constructionCostTotal() + inflationCostValue()
}

function constructionCostInclInflationValue() {
	if (outputs) return outputs.costs.constructionCostInclInflationAed
	return inputs.constructionCostOverrideAed ?? rawConstructionCostInclInflation()
}

function rawDesignSupervisionCost() {
	return constructionCostTotal() * (inputs.designSupervisionPct / 100)
}

function designSupervisionCostValue() {
	if (outputs) return outputs.costs.designSupervisionCostAed
	return inputs.designSupervisionCostOverrideAed ?? rawDesignSupervisionCost()
}

function rawMarketingCost() {
	return totalConfiguredRevenueValue() * (inputs.marketingCostPct / 100)
}

function marketingCostValue() {
	if (outputs) return outputs.costs.marketingCostAed
	return inputs.marketingCostOverrideAed ?? rawMarketingCost()
}

function rawSalesAgentFees() {
	return totalConfiguredRevenueValue() * (inputs.salesAgentFeePct / 100)
}

function salesAgentFeesValue() {
	if (outputs) return outputs.costs.salesAgentFeesAed
	return inputs.salesAgentFeesOverrideAed ?? rawSalesAgentFees()
}

function rawContingencyCost() {
	return constructionCostTotal() * (inputs.contingencyPct / 100)
}

function contingencyCostValue() {
	if (outputs) return outputs.costs.contingencyCostAed
	return inputs.contingencyCostOverrideAed ?? rawContingencyCost()
}

function demolitionCostValue() {
	if (outputs) return outputs.costs.demolitionCostAed
	return inputs.demolitionEnabled ? inputs.demolitionCostAed : 0
}

function totalCostsExclVatValue() {
	if (outputs) return outputs.costs.totalCostsExclVatAed
	return (
		totalLandCostAedValue() +
		designSupervisionCostValue() +
		demolitionCostValue() +
		constructionCostInclInflationValue() +
		inputs.infrastructureCostAed +
		inputs.governmentFeesAed +
		marketingCostValue() +
		salesAgentFeesValue() +
		inputs.masterCommunityFeesAed +
		inputs.ffeOsePreopeningCostAed +
		contingencyCostValue()
	)
}

function vatAmountValue() {
	if (outputs) return outputs.costs.vatAmountAed
	return totalCostsExclVatValue() * (inputs.vatPct / 100)
}

function totalCostsInclVatValue() {
	if (outputs) return outputs.costs.totalCostsInclVatAed
	return totalCostsExclVatValue() + vatAmountValue()
}

function modelTotalCostsInclVatValue() {
	return outputs?.costs.totalCostsInclVatAed ?? totalCostsInclVatValue()
}

function totalDebtCapacityValue() {
	if (outputs) return outputs.funding.totalDebtCapacityAed
	return totalCostsInclVatValue() * inputs.debtToCostRatio
}

function landLoanCapacityValue() {
	if (outputs) return outputs.funding.landLoanCapacityAed
	return Math.min(
		plotAcquisitionCostValue() * (inputs.landLoanLtvPct / 100),
		totalDebtCapacityValue()
	)
}

function constructionLoanCapacityValue() {
	if (outputs) return outputs.funding.constructionLoanCapacityAed
	return Math.max(totalDebtCapacityValue() - landLoanCapacityValue(), 0)
}

function fundingDebtValue() {
	return outputs?.funding?.debtFundingAed ?? totalDebtCapacityValue()
}

function fundingEquityValue() {
	return (
		outputs?.funding?.equityFundingAed ?? Math.max(totalCostsInclVatValue() - fundingDebtValue(), 0)
	)
}

function fundingLandLoanValue() {
	return outputs?.funding?.landLoanCapacityAed ?? landLoanCapacityValue()
}

function fundingConstructionLoanValue() {
	return outputs?.funding?.constructionLoanCapacityAed ?? constructionLoanCapacityValue()
}

function debtCoverageRatio() {
	const debtEligible =
		constructionCostInclInflationValue() +
		designSupervisionCostValue() +
		marketingCostValue() +
		salesAgentFeesValue() +
		vatAmountValue()
	return debtEligible > 0 ? Math.min(1, fundingDebtValue() / debtEligible) : 0
}

function debtConstructionValue() {
	return constructionCostInclInflationValue() * debtCoverageRatio()
}

function debtDesignSupervisionValue() {
	return designSupervisionCostValue() * debtCoverageRatio()
}

function debtMarketingSalesValue() {
	return (marketingCostValue() + salesAgentFeesValue()) * debtCoverageRatio()
}

function debtVatValue() {
	return vatAmountValue() * debtCoverageRatio()
}

function equityLandValue() {
	return Math.max(totalLandCostAedValue() - fundingLandLoanValue(), 0)
}

function equityOtherCostsValue() {
	return (
		(inputs.infrastructureCostAed +
			inputs.governmentFeesAed +
			inputs.masterCommunityFeesAed +
			inputs.ffeOsePreopeningCostAed +
			contingencyCostValue() +
			demolitionCostValue()) *
		(1 - debtCoverageRatio())
	)
}

function equityConstructionValue() {
	return (
		(constructionCostInclInflationValue() +
			designSupervisionCostValue() +
			marketingCostValue() +
			salesAgentFeesValue() +
			vatAmountValue()) *
		(1 - debtCoverageRatio())
	)
}

function offPlanSalesProceedsValue() {
	const depositPct = inputs.paymentPlan.depositPct
	const prePct = inputs.paymentPlan.constructionPct
	return (
		outputs?.funding?.offPlanProceedsAed ??
		totalConfiguredRevenueValue() * ((depositPct + prePct) / 100)
	)
}

function vatRefundsValue() {
	return outputs?.funding?.vatRefundsAed ?? vatAmountValue()
}

function sourcesOfFundsTotalValue() {
	return (
		outputs?.funding?.totalSourcesAed ??
		offPlanSalesProceedsValue() +
			inputs.debtFundingAed +
			inputs.equityFundingAed +
			vatRefundsValue()
	)
}

function usesOfFundingTotalValue() {
	return outputs?.funding?.totalUsesAed ?? modelTotalCostsInclVatValue()
}

function returnOnCostPctValue() {
	const revenue = totalConfiguredRevenueValue()
	const profit = revenue - modelTotalCostsInclVatValue()
	return (
		outputs?.returns?.grossMarginPct ??
		(modelTotalCostsInclVatValue() > 0 ? (profit / modelTotalCostsInclVatValue()) * 100 : 0)
	)
}

function revenueMultipleValue() {
	return (
		outputs?.returns?.projectMoic ??
		(modelTotalCostsInclVatValue() > 0
			? totalConfiguredRevenueValue() / modelTotalCostsInclVatValue()
			: 0)
	)
}

function projectIrrPctValue() {
	return outputs?.returns?.projectIrrPct ?? null
}

function landLoanRatePctValue() {
	return inputs.eiborRatePct + inputs.landLoanSpreadBps / 100
}

function constructionLoanRatePctValue() {
	return inputs.eiborRatePct + inputs.constructionLoanSpreadBps / 100
}

function buaRateAllInValue() {
	const buaSqft = toSqft(totalBuaSqmValue())
	return buaSqft > 0 ? modelTotalCostsInclVatValue() / buaSqft : 0
}

function hasDraftCaseValue() {
	return outputs !== null
}

function setReviewDecision(code: string, decision: ReviewDecisionType | null): void {
	if (decision === null) delete reviewDecisions[code]
	else reviewDecisions[code] = { code, decision, timestamp: new Date().toISOString() }
}

function getReviewDecision(code: string): ReviewDecision | null {
	return reviewDecisions[code] ?? null
}

function applyAssumptionsPatch(patch: Partial<FeasibilityAssumptions>): void {
	if (!state.assumptions) return
	state.assumptions = { ...state.assumptions, ...patch }
}

function applyUnitConfigPatch(id: string, patch: Partial<UnitConfig>): void {
	if (!state.assumptions) return
	state.assumptions = {
		...state.assumptions,
		unitConfigs: state.assumptions.unitConfigs.map((row) =>
			row.id === id ? { ...row, ...patch } : row
		)
	}
}

function applyPaymentPlanPatch(patch: Partial<FeasibilityAssumptions['paymentPlan']>): void {
	if (!state.assumptions) return
	state.assumptions = {
		...state.assumptions,
		paymentPlan: { ...state.assumptions.paymentPlan, ...patch }
	}
}

// ── Actions ──────────────────────────────────────────────────────────────────

function initFromPlot(plotData: PlotDetails): void {
	state.phase = 'ready'
	state.plotData = plotData
	state.assumptions = seedAssumptionsFromPlot(plotData)
	state.study_context = {
		headline: plotData.project_name,
		project_tier: 'premium',
		positioning: 'Seeded study pending generation',
		summary_points: [],
		unit_mix_rationale: '',
		pricing_rationale: '',
		cost_rationale: '',
		timing_rationale: '',
		financing_rationale: '',
		market_summary: ''
	}
	state.research = {
		plot_number: plotData.plot_number,
		usage: plotData.inferred_usage ?? 'unknown',
		market_area: plotData.community_name,
		headline: plotData.project_name,
		summary: [],
		constraints: [],
		warnings: [],
		pricing_evidence: [],
		competition_evidence: [],
		land_sales_evidence: [],
		market_pricing: [],
		off_plan_market_pricing: [],
		off_plan_pricing_confidence: null,
		off_plan_unit_benchmarks: [],
		assumptions: seedAssumptionsFromPlot(plotData) as never,
		land_cost_estimate_aed_low: null,
		land_cost_estimate_aed_mid: null,
		land_cost_estimate_aed_high: null
	}
	state.error = null
}

function loadStudy(data: {
	plotData: PlotDetails
	assumptions: FeasibilityAssumptions
	study_context: StudyContext
	research: PlotResearch
}): void {
	state.phase = 'ready'
	state.plotData = data.plotData
	state.assumptions = data.assumptions
	state.study_context = data.study_context
	state.research = data.research
	state.error = null
}

function updateAssumptions(patch: Partial<FeasibilityAssumptions>): void {
	applyAssumptionsPatch(patch)
}

function updateInputs(patch: Partial<FeasibilityAssumptions>): void {
	const impactedTabs = new Set<FeasibilitySheetTab>(['key_assumptions'])
	for (const key of Object.keys(patch) as Array<keyof FeasibilityAssumptions>) {
		if (EIBOR_IMPACT_KEYS.has(key)) {
			for (const tab of EIBOR_IMPACT_SHEETS) impactedTabs.add(tab)
		}
		if (BUDGET_IMPACT_KEYS.has(key)) {
			for (const tab of BUDGET_IMPACT_SHEETS) impactedTabs.add(tab)
		}
		if (
			key === 'debtToCostRatio' ||
			key === 'presaleThresholdPct' ||
			key === 'escrowRetentionPct' ||
			key === 'arrangementFeePct' ||
			key === 'commitmentFeePct' ||
			key === 'debtRepaymentMode' ||
			key === 'debtFundingAed' ||
			key === 'equityFundingAed' ||
			key === 'landLoanLtvPct'
		) {
			for (const tab of ['financing', 'cashflow', 'monthly_cf', 'returns', 'checks']) {
				impactedTabs.add(tab as FeasibilitySheetTab)
			}
		}
		if (
			key === 'salesCommencementDate' ||
			key === 'salesPeriodMonths' ||
			key === 'constructionDate' ||
			key === 'handoverDate' ||
			key === 'preHandoverMilestoneDate'
		) {
			for (const tab of [
				'sales_collections',
				'budget',
				'financing',
				'cashflow',
				'monthly_cf',
				'returns',
				'checks'
			]) {
				impactedTabs.add(tab as FeasibilitySheetTab)
			}
		}
	}
	markSheetsDirty([...impactedTabs])
	applyAssumptionsPatch(patch)
}

function updateUnitConfig(id: string, patch: Partial<UnitConfig>): void {
	markSheetsDirty(UNIT_MIX_IMPACT_SHEETS)
	applyUnitConfigPatch(id, patch)
}

function updatePaymentPlan(patch: Partial<FeasibilityAssumptions['paymentPlan']>): void {
	markSheetsDirty(PAYMENT_PLAN_IMPACT_SHEETS)
	applyPaymentPlanPatch(patch)
}

function normalizeKey(v: string) {
	return v.trim().toLowerCase().replaceAll(/\s+/g, '').replaceAll('/', '')
}

function applyProposal(proposal: { action: string; payload: unknown }): boolean {
	if (!state.assumptions) return false
	const { action, payload } = proposal
	if (action === 'set_assumptions' && payload && typeof payload === 'object') {
		updateInputs(payload as Partial<FeasibilityAssumptions>)
		return true
	}
	if (action === 'set_price_per_sqm' && payload && typeof payload === 'object') {
		for (const [key, price] of Object.entries(payload as Record<string, number>)) {
			const match = state.assumptions.unitConfigs?.find(
				(r) =>
					normalizeKey(r.id) === normalizeKey(key) || normalizeKey(r.label) === normalizeKey(key)
			)
			if (match) updateUnitConfig(match.id, { sellingRatePsqm: price })
		}
		return true
	}
	if (action === 'set_unit_mix' && Array.isArray(payload)) {
		for (const row of payload as Array<Record<string, unknown>>) {
			const key = String(row.type ?? '')
			const match = state.assumptions.unitConfigs?.find(
				(r) =>
					normalizeKey(r.id) === normalizeKey(key) || normalizeKey(r.label) === normalizeKey(key)
			)
			if (match)
				updateUnitConfig(match.id, {
					units: typeof row.count === 'number' ? row.count : match.units,
					avgSizeSqm: typeof row.avgSizeSqm === 'number' ? row.avgSizeSqm : match.avgSizeSqm,
					sellingRatePsqm:
						typeof row.price_sqm === 'number' ? row.price_sqm : match.sellingRatePsqm,
					parkingRatio: typeof row.parkingRatio === 'number' ? row.parkingRatio : match.parkingRatio
				})
		}
		return true
	}
	if (
		action === 'set_payment_plan' &&
		payload &&
		typeof payload === 'object' &&
		!Array.isArray(payload)
	) {
		updatePaymentPlan(payload as Partial<FeasibilityAssumptions['paymentPlan']>)
		return true
	}
	return false
}

function setError(message: string): void {
	state.phase = 'error'
	state.error = message
}

function reset(): void {
	state.phase = 'empty'
	state.plotData = null
	state.assumptions = null
	state.study_context = null
	state.research = null
	state.error = null
	activeSheet.value = 'key_assumptions'
}

function clearSheetDirty(tab: FeasibilitySheetTab): void {
	sheetDirty[tab] = false
}

function markSheetDirty(tab: FeasibilitySheetTab): void {
	sheetDirty[tab] = true
}

function setActiveSheet(tab: FeasibilitySheetTab): void {
	activeSheet.value = tab
	clearSheetDirty(tab)
}

function currentPlot(): Plot | null {
	const plotData = state.plotData
	if (!plotData) return null
	return {
		plot_number: plotData.plot_number,
		community_name: plotData.community_name,
		project_name: plotData.project_name,
		plot_area_sqm: plotData.plot_area_sqm,
		max_gfa_sqm: plotData.max_gfa_sqm,
		max_height: plotData.max_height,
		max_coverage: plotData.max_coverage,
		gfa_type: plotData.gfa_type,
		is_verified: plotData.is_verified,
		land_use_summary: (plotData.land_use ?? [])
			.map((item) => `${item.type}: ${item.use}`)
			.slice(0, 3)
	}
}

// ── Exports ──────────────────────────────────────────────────────────────────

export const workbookStore = {
	// State
	get phase() {
		return state.phase
	},
	get plotData() {
		return state.plotData
	},
	get plotDetails() {
		return state.plotData
	},
	get plot() {
		return currentPlot()
	},
	get assumptions() {
		return state.assumptions
	},
	get inputs() {
		return inputs
	},
	get study_context() {
		return state.study_context
	},
	get research() {
		return state.research
	},
	get error() {
		return state.error
	},
	get activeSheet() {
		return activeSheet.value
	},
	get sheetDirty() {
		return sheetDirty
	},

	// Rich workbook + clean outputs
	get workbook() {
		return outputs
	},
	get outputs() {
		return outputs
	},
	get validation() {
		return validation
	},

	// Compatibility numeric surfaces used by sheets
	get unitConfigs() {
		return inputs.unitConfigs ?? []
	},
	get paymentPlan() {
		return inputs.paymentPlan
	},
	get maxGfaSqm() {
		return maxGfaSqmValue()
	},
	get totalBuaSqm() {
		return totalBuaSqmValue()
	},
	get totalConfiguredAreaSqm() {
		return totalConfiguredAreaSqmValue()
	},
	get totalUnits() {
		return totalUnitsValue()
	},
	get totalParkingSpaces() {
		return totalParkingSpacesValue()
	},
	get totalConfiguredRevenue() {
		return totalConfiguredRevenueValue()
	},
	get averageSellingPricePsqm() {
		return averageSellingPricePsqmValue()
	},
	get plotAcquisitionCost() {
		return plotAcquisitionCostValue()
	},
	get landTransferFeeAed() {
		return landTransferFeeAedValue()
	},
	get totalLandCostAed() {
		return totalLandCostAedValue()
	},
	get inflationCost() {
		return inflationCostValue()
	},
	get constructionCostInclInflation() {
		return constructionCostInclInflationValue()
	},
	get designSupervisionCost() {
		return designSupervisionCostValue()
	},
	get marketingCost() {
		return marketingCostValue()
	},
	get salesAgentFees() {
		return salesAgentFeesValue()
	},
	get contingencyCost() {
		return contingencyCostValue()
	},
	get demolitionCost() {
		return demolitionCostValue()
	},
	get totalCostsExclVat() {
		return totalCostsExclVatValue()
	},
	get vatAmount() {
		return vatAmountValue()
	},
	get totalCostsInclVat() {
		return totalCostsInclVatValue()
	},
	get modelTotalCostsInclVat() {
		return modelTotalCostsInclVatValue()
	},
	get totalDebtCapacity() {
		return totalDebtCapacityValue()
	},
	get landLoanCapacity() {
		return landLoanCapacityValue()
	},
	get constructionLoanCapacity() {
		return constructionLoanCapacityValue()
	},
	get fundingDebt() {
		return fundingDebtValue()
	},
	get fundingEquity() {
		return fundingEquityValue()
	},
	get fundingLandLoan() {
		return fundingLandLoanValue()
	},
	get fundingConstructionLoan() {
		return fundingConstructionLoanValue()
	},
	get debtConstruction() {
		return debtConstructionValue()
	},
	get debtDesignSupervision() {
		return debtDesignSupervisionValue()
	},
	get debtMarketingSales() {
		return debtMarketingSalesValue()
	},
	get debtVat() {
		return debtVatValue()
	},
	get equityLand() {
		return equityLandValue()
	},
	get equityOtherCosts() {
		return equityOtherCostsValue()
	},
	get equityConstruction() {
		return equityConstructionValue()
	},
	get offPlanSalesProceeds() {
		return offPlanSalesProceedsValue()
	},
	get vatRefunds() {
		return vatRefundsValue()
	},
	get sourcesOfFundsTotal() {
		return sourcesOfFundsTotalValue()
	},
	get usesOfFundingTotal() {
		return usesOfFundingTotalValue()
	},
	get returnOnCostPct() {
		return returnOnCostPctValue()
	},
	get revenueMultiple() {
		return revenueMultipleValue()
	},
	get projectIrrPct() {
		return projectIrrPctValue()
	},
	get irrPct() {
		return projectIrrPctValue()
	},
	get moic() {
		return revenueMultipleValue()
	},
	get landLoanRatePct() {
		return landLoanRatePctValue()
	},
	get constructionLoanRatePct() {
		return constructionLoanRatePctValue()
	},
	get buaRateAllIn() {
		return buaRateAllInValue()
	},
	get hasDraftCase() {
		return hasDraftCaseValue()
	},

	// Review decisions used by assumptions sheet
	get reviewDecisions() {
		return reviewDecisions
	},
	setReviewDecision,
	getReviewDecision,

	// Actions
	initFromPlot,
	loadStudy,
	updateAssumptions,
	updateInputs,
	updateUnitConfig,
	updatePaymentPlan,
	applyProposal,
	setError,
	reset,
	clearSheetDirty,
	markSheetDirty,
	setActiveSheet
}
