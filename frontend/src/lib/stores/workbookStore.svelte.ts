import { feasibility } from '$lib/api/feasibility'
import type {
	Plot,
	PlotDetails,
	PlotResearch,
	StudyContext
} from '$lib/api/generated/hey-api/types.gen'
import {
	buildPricingEvidenceStudy,
	buildResearchSnapshot,
	buildStudyContextCard,
	buildValidationSummary
} from '$lib/feasibility/view-models'
import {
	computeWorkbook as computeWorkbookOutputs,
	type WorkbookOutputs
} from '$lib/feasibility/workbook/engine'
import type {
	FeasibilityAssumptions,
	FeasibilityStudy,
	UnitConfig
} from '$lib/feasibility/workbook/models'
import { type ValidationResult, validateWorkbook } from '$lib/feasibility/workbook/validation'
import { toSqft } from '$lib/utils/units'

type StudyPhase = 'search' | 'generating' | 'ready' | 'error'
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

export type ReviewDecisionType = 'accepted' | 'review_later' | 'needs_evidence'

export interface ReviewDecision {
	code: string
	decision: ReviewDecisionType
	timestamp: string
}

interface FeasibilityStudyState {
	phase: StudyPhase
	selectedPlot: Plot | null
	plotData: PlotDetails | null
	assumptions: FeasibilityAssumptions | null
	study_context: StudyContext | null
	research: PlotResearch | null
	error: string
}

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

function adaptBackendStudy(raw: Record<string, unknown>): FeasibilityStudy {
	const plot_data = raw.plot_data as PlotDetails
	const assumptions = raw.assumptions as FeasibilityAssumptions
	const study_context = raw.study_context as StudyContext
	const research = raw.research as PlotResearch
	return {
		status: 'ready',
		plot_data,
		assumptions,
		study_context,
		research,
		chat: (raw.chat as FeasibilityStudy['chat']) ?? { history: [] }
	}
}

const state = $state<FeasibilityStudyState>({
	phase: 'search',
	selectedPlot: null,
	plotData: null,
	assumptions: null,
	study_context: null,
	research: null,
	error: ''
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
const studyContextCard = $derived(buildStudyContextCard(state.plotData, state.study_context))
const researchSnapshot = $derived(buildResearchSnapshot(state.research))
const validationSummary = $derived(buildValidationSummary(validation))
const pricingEvidenceStudy = $derived(
	buildPricingEvidenceStudy(state.research, state.study_context)
)
const study = $derived<FeasibilityStudy | null>(
	state.plotData && state.assumptions && state.study_context && state.research
		? {
				status: 'ready',
				plot_data: state.plotData,
				assumptions: state.assumptions,
				study_context: state.study_context,
				research: state.research,
				chat: { history: [] }
			}
		: null
)

function resetSheetDirty(): void {
	sheetDirty.key_assumptions = false
	sheetDirty.sales_collections = false
	sheetDirty.budget = false
	sheetDirty.financing = false
	sheetDirty.cashflow = false
	sheetDirty.monthly_cf = false
	sheetDirty.returns = false
	sheetDirty.checks = false
	sheetDirty.pricing_evidence = false
	sheetDirty.eibor = false
}

function resetReviewDecisions(): void {
	for (const key of Object.keys(reviewDecisions)) {
		delete reviewDecisions[key]
	}
}

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

function normalizeKey(v: string) {
	return v.trim().toLowerCase().replaceAll(/\s+/g, '').replaceAll('/', '')
}

function loadStudy(nextStudy: FeasibilityStudy): void {
	state.phase = 'ready'
	state.plotData = nextStudy.plot_data
	state.assumptions = nextStudy.assumptions
	state.study_context = nextStudy.study_context
	state.research = nextStudy.research
	state.error = ''
	activeSheet.value = 'key_assumptions'
	resetSheetDirty()
	resetReviewDecisions()
}

function updateAssumptions(patch: Partial<FeasibilityAssumptions>): void {
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

function applyProposal(proposal: { action: string; payload: unknown }): boolean {
	if (!state.assumptions) return false
	const { action, payload } = proposal
	if (action === 'set_assumptions' && payload && typeof payload === 'object') {
		updateAssumptions(payload as Partial<FeasibilityAssumptions>)
		return true
	}
	if (action === 'set_price_per_sqm' && payload && typeof payload === 'object') {
		for (const [key, price] of Object.entries(payload as Record<string, number>)) {
			const match = state.assumptions.unitConfigs?.find(
				(row) =>
					normalizeKey(row.id) === normalizeKey(key) ||
					normalizeKey(row.label) === normalizeKey(key)
			)
			if (match) updateUnitConfig(match.id, { sellingRatePsqm: price })
		}
		return true
	}
	if (action === 'set_unit_mix' && Array.isArray(payload)) {
		for (const row of payload as Array<Record<string, unknown>>) {
			const key = String(row.type ?? '')
			const match = state.assumptions.unitConfigs?.find(
				(item) =>
					normalizeKey(item.id) === normalizeKey(key) ||
					normalizeKey(item.label) === normalizeKey(key)
			)
			if (match) {
				updateUnitConfig(match.id, {
					units: typeof row.count === 'number' ? row.count : match.units,
					avgSizeSqm: typeof row.avgSizeSqm === 'number' ? row.avgSizeSqm : match.avgSizeSqm,
					sellingRatePsqm:
						typeof row.price_sqm === 'number' ? row.price_sqm : match.sellingRatePsqm,
					parkingRatio: typeof row.parkingRatio === 'number' ? row.parkingRatio : match.parkingRatio
				})
			}
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

export const workbookStore = {
	get phase() {
		return state.phase
	},
	get selectedPlot() {
		return state.selectedPlot
	},
	get plotData() {
		return state.plotData
	},
	get study() {
		return study
	},
	get assumptions() {
		return inputs
	},
	get studyContext() {
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
	get outputs() {
		return outputs
	},
	get validation() {
		return validation
	},
	get studyContextCard() {
		return studyContextCard
	},
	get researchSnapshot() {
		return researchSnapshot
	},
	get validationSummary() {
		return validationSummary
	},
	get pricingEvidenceStudy() {
		return pricingEvidenceStudy
	},
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
	get reviewDecisions() {
		return reviewDecisions
	},
	setReviewDecision,
	getReviewDecision,
	async selectPlot(plot: Plot) {
		state.selectedPlot = plot
		state.phase = 'search'
		state.error = ''
		state.plotData = null
		state.assumptions = null
		state.study_context = null
		state.research = null
		activeSheet.value = 'key_assumptions'
		resetSheetDirty()
		resetReviewDecisions()
		try {
			const response = await feasibility.getPlotData(plot.plot_number)
			state.plotData = response.plot_data
		} catch (err) {
			state.selectedPlot = null
			state.phase = 'error'
			state.error = err instanceof Error ? err.message : 'Failed to load plot data.'
		}
	},
	async generateStudy() {
		const plot = state.selectedPlot
		if (!plot) return
		state.phase = 'generating'
		state.error = ''
		try {
			const next = await feasibility.generateStudy({
				plot_number: plot.plot_number,
				usage_override: state.plotData?.inferred_usage ?? undefined
			})
			loadStudy(adaptBackendStudy(next as unknown as Record<string, unknown>))
		} catch (err) {
			state.phase = 'error'
			state.error = err instanceof Error ? err.message : 'Failed to generate feasibility study.'
		}
	},
	loadStudy,
	updateAssumptions,
	updateUnitConfig,
	updatePaymentPlan,
	applyProposal,
	setError(message: string): void {
		state.phase = 'error'
		state.error = message
	},
	clearSheetDirty(tab: FeasibilitySheetTab): void {
		sheetDirty[tab] = false
	},
	markSheetDirty(tab: FeasibilitySheetTab): void {
		sheetDirty[tab] = true
	},
	setActiveSheet(tab: FeasibilitySheetTab): void {
		activeSheet.value = tab
		sheetDirty[tab] = false
	},
	reset() {
		state.phase = 'search'
		state.selectedPlot = null
		state.plotData = null
		state.assumptions = null
		state.study_context = null
		state.research = null
		state.error = ''
		activeSheet.value = 'key_assumptions'
		resetSheetDirty()
		resetReviewDecisions()
	}
}
