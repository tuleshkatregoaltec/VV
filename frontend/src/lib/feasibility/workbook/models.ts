import type {
	Plot,
	PlotDetails,
	PlotResearch,
	StudyContext
} from '$lib/api/generated/hey-api/types.gen'

export type { Plot, PlotDetails, PlotResearch, StudyContext }

// ── Canonical model input ────────────────────────────────────────────────────
// FeasibilityAssumptions is the authoritative input contract for computeWorkbook.

export type UsageType = 'residential' | 'commercial' | 'mixed_use' | 'unknown'
export type DebtRepaymentMode = 'bullet_at_handover' | 'sales_sweep'

export interface FeasibilityPaymentPlan {
	depositPct: number
	constructionPct: number
	handoverPct: number
}

export interface UnitConfig {
	id: string
	label: string
	units: number
	avgSizeSqm: number
	sellingRatePsqm: number
	parkingRatio: number
}

export interface FeasibilityAssumptions {
	// Usage — drives area chain benchmarks; seeded from research, editable
	usage: UsageType

	// Plot / area — seeded from plot_data, used by area chain calculations
	plotAreaSqm: number
	maxGfaSqm: number // regulatory max GFA; seeded from plot_data.max_gfa_sqm
	maxCoveragePct: number | null // regulatory max coverage; seeded from plot_data.max_coverage (parsed)
	maxStoreys: number | null // regulatory max storeys; seeded from plot_data.max_height (parsed)
	maxFar: number

	// Plot display metadata — seeded from plot_data
	plotNumber?: string
	communityName?: string
	projectName?: string
	gfaType?: string | null
	sitePlanIssueDate?: string | null
	sitePlanExpiryDate?: string | null
	plotWarnings?: string[]

	buaMultiplier: number
	nsaEfficiencyPct: number
	numberOfTowers: number
	numberOfFloors: number

	// Unit mix
	unitConfigs: UnitConfig[]
	paymentPlan: FeasibilityPaymentPlan

	// Parking
	standardParkingRatio: number
	largeUnitThresholdSqm: number
	largeUnitParkingRatio: number

	// Land costs
	landPricePsqm: number
	landAcquisitionCostOverrideAed: number | null
	brokerageFeeAed: number
	legalDdCostAed: number

	// Construction
	constructionCostPsqmBua: number
	constructionCostOverrideAed: number | null
	midPointInflationPct: number

	// Professional fees
	designSupervisionPct: number
	designSupervisionCostOverrideAed: number | null

	// Selling costs
	marketingCostPct: number
	marketingCostOverrideAed: number | null
	salesAgentFeePct: number
	salesAgentFeesOverrideAed: number | null

	// Other direct costs
	infrastructureCostAed: number
	governmentFeesAed: number
	masterCommunityFeesAed: number
	ffeOsePreopeningCostAed: number
	contingencyPct: number
	contingencyCostOverrideAed: number | null
	demolitionEnabled: boolean
	demolitionCostAed: number
	vatPct: number

	// Financing
	debtToCostRatio: number
	landLoanLtvPct: number
	eiborRatePct: number
	landLoanSpreadBps: number
	constructionLoanSpreadBps: number
	arrangementFeePct: number
	commitmentFeePct: number
	presaleThresholdPct: number
	escrowRetentionPct: number
	debtRepaymentMode: DebtRepaymentMode
	debtFundingAed: number
	equityFundingAed: number
	financeRatePct: number

	// Schedule
	landAcquisitionDate: string
	demolitionEnablingDate: string
	salesCommencementDate: string
	salesPeriodMonths: number
	constructionDate: string
	handoverDate: string
	preHandoverMilestoneDate: string
}

export interface FeasibilityChatMessage {
	role: 'system' | 'user' | 'assistant'
	content: string
}

// ── Workbook-first study shape ───────────────────────────────────────────────
// assumptions is the canonical mutable model.
// outputs is derived reactively from assumptions by computeWorkbook.
// study_context and research are secondary — display and evidence, not model inputs.

export interface FeasibilityStudy {
	status: 'ready'
	plot_data: PlotDetails
	assumptions: FeasibilityAssumptions
	study_context: StudyContext
	research: PlotResearch
	chat: {
		history: FeasibilityChatMessage[]
	}
}

export interface PlotDataResponse {
	plot_data: PlotDetails
}
