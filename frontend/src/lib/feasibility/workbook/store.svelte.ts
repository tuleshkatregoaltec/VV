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
	| 'summary'
	| 'sales_collections'
	| 'area_bridge'
	| 'massing'
	| 'budget'
	| 'sources_uses'
	| 'financing'
	| 'monthly_cf'
	| 'cashflow'
	| 'returns'
	| 'waterfall'
	| 'vat_bridge'
	| 'milestones'
	| 'eibor'
	| 'checks'
	| 'pricing_evidence'
	| 'btr_operating'

export interface WorkbookState {
	phase: WorkbookPhase
	plotData: PlotDetails | null
	assumptions: FeasibilityAssumptions | null
	study_context: StudyContext | null
	research: PlotResearch | null
	error: string | null
}

// ── Dirty tracking sets ──────────────────────────────────────────────────────

// Sheets impacted by most cost/revenue/financing changes
const DOWNSTREAM_SHEETS: FeasibilitySheetTab[] = [
	'summary',
	'massing',
	'budget',
	'financing',
	'monthly_cf',
	'returns',
	'checks'
]

const UNIT_MIX_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'key_assumptions',
	'summary',
	'sales_collections',
	'massing',
	'budget',
	'financing',
	'monthly_cf',
	'returns',
	'checks'
]

const PAYMENT_PLAN_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'key_assumptions',
	'summary',
	'sales_collections',
	'financing',
	'monthly_cf',
	'returns',
	'checks'
]

const EIBOR_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'eiborRatePct',
	'landLoanSpreadBps',
	'constructionLoanSpreadBps',
	'debtSpreadPa'
])

const EIBOR_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'eibor',
	'summary',
	'financing',
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
	'handoverDate',
	// New template fields
	'landTransferFeePct',
	'brokeragePct',
	'legalDdPct',
	'permitFeesPct',
	'softCostPct',
	'btrLeaseUpMarketingAed',
	'btrDevCostEscalationPct'
])

const BUDGET_IMPACT_SHEETS: FeasibilitySheetTab[] = [
	'summary',
	'budget',
	'financing',
	'monthly_cf',
	'returns',
	'checks'
]

const AREA_BRIDGE_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'basementParkingFloors',
	'podiumFloors',
	'residentialFloors',
	'amenityRoofFloors',
	'parkingAreaPerSpaceSqm',
	'aboveGradeBuaFactor',
	'serviceBohPlantPct',
	'podiumParkingFloorsOutsideGfa',
	'buaMultiplier',
	'nsaEfficiencyPct',
	'maxGfaSqm',
	'plotAreaSqm',
	'maxCoveragePct',
	'maxStoreys',
	'targetCoveragePct',
	'targetBuildingCount',
	'maxEfficientTowerFloorplateSqm',
	'minEfficientTowerFloorplateSqm',
	'floorToFloorHeightM',
	'podiumFloorToFloorHeightM',
	'groundFloorHeightM',
	'roofPlantAllowanceM'
])

const FINANCING_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'debtToCostRatio',
	'presaleThresholdPct',
	'escrowRetentionPct',
	'arrangementFeePct',
	'commitmentFeePct',
	'debtRepaymentMode',
	'debtFundingAed',
	'equityFundingAed',
	'landLoanLtvPct',
	// New dual-tranche fields
	'acquisitionDebtLtv',
	'constructionDebtLtc',
	'financingFeePct',
	'exitFeePct',
	'btrPermDebtLtvPct',
	'btrPermDebtSpreadBps',
	'btrPermDebtAmortYears',
	'btrPermDebtPointsPct',
	'btrPermDebtIoYears',
	'btrDscrMinimum',
	'btrRefiCapRatePct'
])

const VAT_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>(['vatPct', 'vatRefundLagMonths'])

const WATERFALL_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'preferredReturnPa',
	'sponsorPromotePct',
	'projectYears'
])

const CURVE_IMPACT_KEYS = new Set<keyof FeasibilityAssumptions>([
	'constructionCurveSteepness',
	'salesCurveSteepness'
])

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
		paymentPlan: { depositPct: 10, constructionPct: 30, handoverPct: 60 },
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
		landLoanLtvPct: 70,
		eiborRatePct: 4.85,
		landLoanSpreadBps: 200,
		constructionLoanSpreadBps: 200,
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
		preHandoverMilestoneDate: todayIsoDate(),

		// Building configuration (Area Bridge)
		basementParkingFloors: 4,
		podiumFloors: 5,
		residentialFloors: 30,
		amenityRoofFloors: 1,
		parkingAreaPerSpaceSqm: 30,

		// Area Bridge inputs
		aboveGradeBuaFactor: 1.1,
		serviceBohPlantPct: 0.03,
		podiumParkingFloorsOutsideGfa: 0,

		// Template-aligned cost percentages
		landTransferFeePct: 0.04,
		brokeragePct: 0.01,
		legalDdPct: 0.005,
		permitFeesPct: 0.02,
		softCostPct: 0.15,

		// Dual-tranche financing
		acquisitionDebtLtv: 0.7,
		constructionDebtLtc: 0.7,
		debtSpreadPa: 0.02,
		financingFeePct: 0.01,
		exitFeePct: 0.01,

		// Equity waterfall
		preferredReturnPa: 0.08,
		sponsorPromotePct: 0.2,
		projectYears: 5,

		// S-curve configuration
		constructionCurveSteepness: 8,
		salesCurveSteepness: 8,

		// VAT per-category applicability
		vatAppliesTo: {
			land: true,
			hardCosts: true,
			softCosts: true,
			permitFees: true,
			contingency: true,
			marketing: true,
			salesAdmin: true
		},
		vatRefundLagMonths: 6,

		// Scenario
		selectedScenario: 'base',
		developmentModel: 'build_to_sell_residential',
		btrHoldPeriodYears: 10,
		btrLeaseUpPaceUnitsPerMonth: 20,
		btrStabilizedOccupancyPct: 95,
		btrFreeRentMonths: 2,
		btrAnnualRentGrowthPct: 3,
		btrMarketRentGrowthPct: 3,
		btrRenewalRentGrowthPct: 3,
		btrGeneralVacancyPct: 5,
		btrPropertyManagementPct: 5,
		btrRepairsMaintenancePsqm: 50,
		btrInsurancePsqm: 10,
		btrServiceChargePsqm: 80,
		btrUtilitiesPsqm: 30,
		btrMarketingLeasingPct: 2,
		btrCapexReservePct: 5,
		btrParkingIncomeAed: 0,
		btrAncillaryIncomeAed: 0,
		btrAncillaryGrowthPct: 3,
		btrStabilizedFreeRentMonths: 0,
		btrOpExGrowthPct: 3,
		btrDevCostEscalationPct: 4,
		btrTerminalGrowthPct: 3,
		btrLeaseUpMarketingAed: 0,
		btrCreditLossPct: 1,
		btrPayrollPsqm: 40,
		btrGeneralAdminPct: 1,
		btrContractServicesPsqm: 25,
		btrModelUnits: 1,
		btrExitCapRatePct: 7,
		btrExitCostPct: 6,
		btrPermDebtLtvPct: 65,
		btrPermDebtSpreadBps: 165,
		btrPermDebtAmortYears: 25,
		btrPermDebtPointsPct: 1,
		btrPermDebtIoYears: 1,
		btrDscrMinimum: 1.25,
		btrRefiCapRatePct: 7
	}
}

function normalizeAssumptions(raw: FeasibilityAssumptions): FeasibilityAssumptions {
	const defaults = createDefaultAssumptions()
	const normalized: FeasibilityAssumptions = {
		...defaults,
		...raw,
		paymentPlan: {
			...defaults.paymentPlan,
			...(raw.paymentPlan ?? {})
		},
		vatAppliesTo: {
			...defaults.vatAppliesTo,
			...(raw.vatAppliesTo ?? {})
		} as FeasibilityAssumptions['vatAppliesTo']
	}

	if (
		normalized.developmentModel === 'build_to_rent_residential' &&
		(normalized.btrUnitConfigs?.length ?? 0) > 0
	) {
		normalized.unitConfigs = (normalized.btrUnitConfigs ?? []).map((cfg, index) => ({
			id: cfg.id || `btr-${index + 1}`,
			label: cfg.label || `Rental ${index + 1}`,
			units: cfg.units,
			avgSizeSqm: cfg.avgSizeSqm,
			sellingRatePsqm: 0,
			parkingRatio: cfg.parkingRatio
		}))
		normalized.marketingCostPct = 0
		normalized.salesAgentFeePct = 0
		normalized.marketingCostOverrideAed = 0
		normalized.salesAgentFeesOverrideAed = 0
	}

	if (
		(normalized.acquisitionDebtLtv === undefined || normalized.acquisitionDebtLtv === null) &&
		Number.isFinite(normalized.landLoanLtvPct)
	) {
		normalized.acquisitionDebtLtv = normalized.landLoanLtvPct / 100
	}

	if (Number.isFinite(normalized.acquisitionDebtLtv)) {
		normalized.landLoanLtvPct = Math.round((normalized.acquisitionDebtLtv ?? 0) * 100)
	}

	if (
		(normalized.debtSpreadPa === undefined || normalized.debtSpreadPa === null) &&
		Number.isFinite(normalized.constructionLoanSpreadBps)
	) {
		normalized.debtSpreadPa = normalized.constructionLoanSpreadBps / 10_000
	}

	if (
		(normalized.landLoanSpreadBps === undefined || normalized.landLoanSpreadBps === null) &&
		normalized.debtSpreadPa !== undefined &&
		normalized.debtSpreadPa !== null
	) {
		const spreadBps = Math.round(normalized.debtSpreadPa * 10_000)
		normalized.landLoanSpreadBps = spreadBps
	}

	if (
		(normalized.constructionLoanSpreadBps === undefined ||
			normalized.constructionLoanSpreadBps === null) &&
		normalized.debtSpreadPa !== undefined &&
		normalized.debtSpreadPa !== null
	) {
		const spreadBps = Math.round(normalized.debtSpreadPa * 10_000)
		normalized.constructionLoanSpreadBps = spreadBps
	}

	return normalized
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
	return normalizeAssumptions({
		...base,
		usage: plotData.inferred_usage ?? 'unknown',
		plotAreaSqm: plotData.plot_area_sqm,
		maxGfaSqm: plotData.max_gfa_sqm ?? 0,
		maxCoveragePct: parseMaxCoverage(plotData.max_coverage),
		maxStoreys: parseMaxStoreys(plotData.max_height),
		maxFar: plotData.far ?? 0
	})
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
	summary: false,
	sales_collections: false,
	area_bridge: false,
	massing: false,
	budget: false,
	sources_uses: false,
	financing: false,
	monthly_cf: false,
	cashflow: false,
	returns: false,
	waterfall: false,
	vat_bridge: false,
	milestones: false,
	eibor: false,
	checks: false,
	pricing_evidence: false,
	btr_operating: false
})

const activeSheet = $state<{ value: FeasibilitySheetTab }>({
	value: 'key_assumptions'
})

const reviewDecisions = $state<Record<string, ReviewDecision>>({})

const inputs = $derived<FeasibilityAssumptions>(state.assumptions ?? createDefaultAssumptions())

// ── Debounced computation ────────────────────────────────────────────────────
// Avoid recomputing the entire workbook on every keystroke.
// Uses $state + $effect with a 150ms debounce timer.
const DEBOUNCE_MS = 150

const computedState = $state<{
	outputs: WorkbookOutputs | null
	validation: ValidationResult | null
}>({ outputs: null, validation: null })

let debounceTimer: ReturnType<typeof setTimeout> | null = null

function clearPendingWorkbookRecompute(): void {
	if (!debounceTimer) return
	clearTimeout(debounceTimer)
	debounceTimer = null
}

function clearComputedWorkbookState(): void {
	computedState.outputs = null
	computedState.validation = null
}

function runWorkbookRecompute(assumptions: FeasibilityAssumptions): void {
	try {
		const out = computeWorkbookOutputs(assumptions)
		const val = validateWorkbook(assumptions, out)
		computedState.outputs = out
		computedState.validation = val
	} catch (err) {
		console.error('[workbook] computation failed:', err)
		computedState.outputs = null
		computedState.validation = null
	}
}

function scheduleWorkbookRecompute(assumptions: FeasibilityAssumptions | null | undefined): void {
	clearPendingWorkbookRecompute()
	if (!assumptions) {
		clearComputedWorkbookState()
		return
	}

	const assumptionsSnapshot = assumptions
	debounceTimer = setTimeout(() => {
		runWorkbookRecompute(assumptionsSnapshot)
		debounceTimer = null
	}, DEBOUNCE_MS)
}

// Convenience accessors (keep existing API surface)
const outputs = $derived(computedState.outputs)
const validation = $derived(computedState.validation)

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
	return landLoanCapacityValue() + constructionLoanCapacityValue()
}

function landLoanCapacityValue() {
	if (outputs) return outputs.funding.landLoanCapacityAed
	const acquisitionLtv = inputs.acquisitionDebtLtv ?? inputs.landLoanLtvPct / 100
	return totalLandCostAedValue() * acquisitionLtv
}

function constructionLoanCapacityValue() {
	if (outputs) return outputs.funding.constructionLoanCapacityAed
	const constructionLtc = inputs.constructionDebtLtc ?? 0.7
	const permitFees = constructionCostInclInflationValue() * (inputs.permitFeesPct ?? 0.02)
	const eligibleConstructionCosts =
		constructionCostInclInflationValue() +
		designSupervisionCostValue() +
		contingencyCostValue() +
		permitFees
	return eligibleConstructionCosts * constructionLtc
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

// ── Debt allocation — aligned with engine eligibility ────────────────────
// Construction debt covers: permit fees + hard cost + soft cost + contingency
// Marketing, sales admin, VAT, infrastructure, govt fees = equity-funded
// This matches engine.ts:1015-1017 construction eligible categories

function conDebtEligibleTotal() {
	const permitFees = constructionCostInclInflationValue() * (inputs.permitFeesPct ?? 0.02)
	return (
		permitFees +
		constructionCostInclInflationValue() +
		designSupervisionCostValue() +
		contingencyCostValue()
	)
}

function conDebtCoverageRatio() {
	const eligible = conDebtEligibleTotal()
	return eligible > 0 ? Math.min(1, fundingConstructionLoanValue() / eligible) : 0
}

function debtConstructionValue() {
	return constructionCostInclInflationValue() * conDebtCoverageRatio()
}

function debtDesignSupervisionValue() {
	return designSupervisionCostValue() * conDebtCoverageRatio()
}

function debtMarketingSalesValue() {
	// Marketing / sales admin are NOT eligible for construction debt
	return 0
}

function debtVatValue() {
	// VAT is NOT eligible for construction debt
	return 0
}

function equityLandValue() {
	return Math.max(totalLandCostAedValue() - fundingLandLoanValue(), 0)
}

function equityOtherCostsValue() {
	// Infrastructure, govt fees, master community, FF&E, demolition, plus
	// marketing, sales admin, and VAT — all equity-funded
	return (
		inputs.infrastructureCostAed +
		inputs.governmentFeesAed +
		inputs.masterCommunityFeesAed +
		inputs.ffeOsePreopeningCostAed +
		demolitionCostValue() +
		marketingCostValue() +
		salesAgentFeesValue() +
		vatAmountValue()
	)
}

function equityConstructionValue() {
	// Equity portion of construction-eligible costs (what debt doesn't cover)
	return (
		(constructionCostInclInflationValue() + designSupervisionCostValue() + contingencyCostValue()) *
		(1 - conDebtCoverageRatio())
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
		outputs?.funding?.cashReconSourcesAed ??
		offPlanSalesProceedsValue() + fundingDebtValue() + fundingEquityValue() + vatRefundsValue()
	)
}

function usesOfFundingTotalValue() {
	return outputs?.funding?.cashReconUsesAed ?? modelTotalCostsInclVatValue()
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
	const spreadPa =
		inputs.landLoanSpreadBps > 0 ? inputs.landLoanSpreadBps / 10_000 : (inputs.debtSpreadPa ?? 0)
	return inputs.eiborRatePct + spreadPa * 100
}

function constructionLoanRatePctValue() {
	const spreadPa =
		inputs.constructionLoanSpreadBps > 0
			? inputs.constructionLoanSpreadBps / 10_000
			: (inputs.debtSpreadPa ?? 0)
	return inputs.eiborRatePct + spreadPa * 100
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
	const nextPatch = { ...patch }
	if (patch.acquisitionDebtLtv != null) {
		nextPatch.landLoanLtvPct = Math.round(patch.acquisitionDebtLtv * 100)
	}
	if (patch.landLoanLtvPct != null) {
		nextPatch.acquisitionDebtLtv = patch.landLoanLtvPct / 100
	}
	if (patch.debtSpreadPa != null) {
		const spreadBps = Math.round(patch.debtSpreadPa * 10_000)
		nextPatch.landLoanSpreadBps = spreadBps
		nextPatch.constructionLoanSpreadBps = spreadBps
	}
	state.assumptions = normalizeAssumptions({ ...state.assumptions, ...nextPatch })
	scheduleWorkbookRecompute(state.assumptions)
}

function applyUnitConfigPatch(id: string, patch: Partial<UnitConfig>): void {
	if (!state.assumptions) return
	state.assumptions = {
		...state.assumptions,
		unitConfigs: state.assumptions.unitConfigs.map((row) =>
			row.id === id ? { ...row, ...patch } : row
		)
	}
	scheduleWorkbookRecompute(state.assumptions)
}

function applyPaymentPlanPatch(patch: Partial<FeasibilityAssumptions['paymentPlan']>): void {
	if (!state.assumptions) return
	state.assumptions = {
		...state.assumptions,
		paymentPlan: { ...state.assumptions.paymentPlan, ...patch }
	}
	scheduleWorkbookRecompute(state.assumptions)
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
		rental_market_summary: null,
		rental_comparables: [],
		assumptions: seedAssumptionsFromPlot(plotData) as never,
		land_cost_estimate_aed_low: null,
		land_cost_estimate_aed_mid: null,
		land_cost_estimate_aed_high: null
	}
	state.error = null
	scheduleWorkbookRecompute(state.assumptions)
}

function loadStudy(data: {
	plotData: PlotDetails
	assumptions: FeasibilityAssumptions
	study_context: StudyContext
	research: PlotResearch
}): void {
	state.phase = 'ready'
	state.plotData = data.plotData
	state.assumptions = normalizeAssumptions(data.assumptions)
	state.study_context = data.study_context
	state.research = data.research
	state.error = null
	scheduleWorkbookRecompute(state.assumptions)
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
		if (AREA_BRIDGE_IMPACT_KEYS.has(key)) {
			for (const tab of DOWNSTREAM_SHEETS) impactedTabs.add(tab)
		}
		if (FINANCING_IMPACT_KEYS.has(key)) {
			for (const tab of [
				'summary',
				'financing',
				'monthly_cf',
				'returns',
				'checks'
			] as FeasibilitySheetTab[]) {
				impactedTabs.add(tab)
			}
		}
		if (VAT_IMPACT_KEYS.has(key)) {
			for (const tab of DOWNSTREAM_SHEETS) impactedTabs.add(tab)
		}
		if (WATERFALL_IMPACT_KEYS.has(key)) {
			impactedTabs.add('summary')
			impactedTabs.add('returns')
		}
		if (CURVE_IMPACT_KEYS.has(key)) {
			for (const tab of DOWNSTREAM_SHEETS) impactedTabs.add(tab)
		}
		// vatAppliesTo is an object, handled specially
		if (key === 'vatAppliesTo') {
			for (const tab of DOWNSTREAM_SHEETS) impactedTabs.add(tab)
		}
		if (
			key === 'salesCommencementDate' ||
			key === 'salesPeriodMonths' ||
			key === 'constructionDate' ||
			key === 'handoverDate' ||
			key === 'preHandoverMilestoneDate'
		) {
			for (const tab of [
				'summary',
				'sales_collections',
				'budget',
				'financing',
				'monthly_cf',
				'returns',
				'checks'
			] as FeasibilitySheetTab[]) {
				impactedTabs.add(tab)
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

function removePricingEvidenceAt(index: number): void {
	const research = state.research
	const pricingEvidence = research?.pricing_evidence
	if (!pricingEvidence || index < 0 || index >= pricingEvidence.length) return
	state.research = {
		...research,
		pricing_evidence: pricingEvidence.filter((_, i) => i !== index)
	}
	markSheetDirty('pricing_evidence')
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
	clearPendingWorkbookRecompute()
}

function reset(): void {
	clearPendingWorkbookRecompute()
	state.phase = 'empty'
	state.plotData = null
	state.assumptions = null
	state.study_context = null
	state.research = null
	state.error = null
	activeSheet.value = 'key_assumptions'
	clearComputedWorkbookState()
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
	removePricingEvidenceAt,
	applyProposal,
	setError,
	reset,
	clearSheetDirty,
	markSheetDirty,
	setActiveSheet
}
