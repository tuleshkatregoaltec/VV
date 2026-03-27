import { feasibility } from '$lib/api/feasibility'
import type { Plot } from '$lib/api/generated/hey-api/types.gen'
import type { FeasibilityAssumptions, FeasibilityStudy } from '$lib/feasibility/workbook/models'

type StudyPhase = 'search' | 'generating' | 'ready' | 'error'

const phase = $state({ value: 'search' as StudyPhase })
const selectedPlot = $state({ value: null as Plot | null })
const study = $state({ value: null as FeasibilityStudy | null })
const error = $state({ value: '' })

function todayIsoDate() {
	return new Date().toISOString().slice(0, 10)
}

// Parse max_height string (e.g. "G+12" or "12 storeys") into a number
function parseMaxStoreys(maxHeight: string | null | undefined): number | null {
	if (!maxHeight) return null
	const matches = maxHeight.match(/(\d+)/g)
	if (!matches?.length) return null
	const storeys = Number(matches[matches.length - 1])
	return Number.isFinite(storeys) && storeys > 0 ? storeys : null
}

// Parse max_coverage string (e.g. "60%" or "60") into a percentage number
function parseMaxCoverage(maxCoverage: string | null | undefined): number | null {
	if (!maxCoverage) return null
	const match = maxCoverage.match(/(\d+(?:\.\d+)?)/)
	if (!match) return null
	const value = Number(match[1])
	return Number.isFinite(value) ? value : null
}

function createBaseStudy(plot_data: NonNullable<FeasibilityStudy['plot_data']>): FeasibilityStudy {
	const assumptions: FeasibilityAssumptions = {
		// usage seeded from plot inference; user/agent can override
		usage: plot_data.inferred_usage ?? 'unknown',

		// Plot / area — seeded from plot data
		plotAreaSqm: plot_data.plot_area_sqm,
		maxGfaSqm: plot_data.max_gfa_sqm ?? 0,
		maxCoveragePct: parseMaxCoverage(plot_data.max_coverage),
		maxStoreys: parseMaxStoreys(plot_data.max_height),
		maxFar: plot_data.far ?? 0,
		numberOfTowers: 1,
		numberOfFloors: 1,
		buaMultiplier: 1,
		nsaEfficiencyPct: 80,

		// Unit mix
		unitConfigs: [],
		paymentPlan: { depositPct: 20, constructionPct: 40, handoverPct: 40 },

		// Parking
		standardParkingRatio: 1,
		largeUnitThresholdSqm: 140,
		largeUnitParkingRatio: 2,

		// Land costs
		landPricePsqm: 0,
		landAcquisitionCostOverrideAed: null,
		brokerageFeeAed: 0,
		legalDdCostAed: 0,

		// Construction
		constructionCostPsqmBua: 0,
		constructionCostOverrideAed: null,
		midPointInflationPct: 0,

		// Professional fees
		designSupervisionPct: 0,
		designSupervisionCostOverrideAed: null,

		// Selling costs
		marketingCostPct: 0,
		marketingCostOverrideAed: null,
		salesAgentFeePct: 0,
		salesAgentFeesOverrideAed: null,

		// Other direct costs
		infrastructureCostAed: 0,
		governmentFeesAed: 0,
		masterCommunityFeesAed: 0,
		ffeOsePreopeningCostAed: 0,
		contingencyPct: 0,
		contingencyCostOverrideAed: null,
		demolitionEnabled: false,
		demolitionCostAed: 0,
		vatPct: 5,

		// Financing
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

		// Schedule
		landAcquisitionDate: todayIsoDate(),
		demolitionEnablingDate: todayIsoDate(),
		salesCommencementDate: todayIsoDate(),
		salesPeriodMonths: 24,
		constructionDate: todayIsoDate(),
		handoverDate: todayIsoDate(),
		preHandoverMilestoneDate: todayIsoDate()
	}

	const study_context = {
		headline: plot_data.project_name,
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

	const research = {
		plot_number: plot_data.plot_number,
		usage: plot_data.inferred_usage ?? 'unknown',
		market_area: plot_data.community_name,
		headline: plot_data.project_name,
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
		assumptions: assumptions as never,
		land_cost_estimate_aed_low: null,
		land_cost_estimate_aed_mid: null,
		land_cost_estimate_aed_high: null
	}

	return {
		status: 'ready' as const,
		plot_data,
		assumptions,
		study_context,
		research,
		chat: { history: [] }
	}
}

function adaptBackendStudy(raw: Record<string, unknown>): FeasibilityStudy {
	const assumptions = raw.assumptions as FeasibilityAssumptions
	const research = raw.research as FeasibilityStudy['research']
	const study_context = raw.study_context as FeasibilityStudy['study_context']
	const plot_data = raw.plot_data as FeasibilityStudy['plot_data']
	return {
		status: 'ready',
		plot_data,
		assumptions,
		study_context,
		research,
		chat: (raw.chat as FeasibilityStudy['chat']) ?? { history: [] }
	}
}

function mergeStudy(raw: Record<string, unknown>) {
	study.value = adaptBackendStudy(raw)
	phase.value = 'ready'
	error.value = ''
}

export const feasibilityStudy = {
	get phase() {
		return phase.value
	},
	get selectedPlot() {
		return selectedPlot.value
	},
	get study() {
		return study.value
	},
	get error() {
		return error.value
	},
	get plotData() {
		return study.value?.plot_data ?? null
	},
	async selectPlot(plot: Plot) {
		selectedPlot.value = plot
		error.value = ''
		phase.value = 'search'
		const response = await feasibility.getPlotData(plot.plot_number)
		study.value = createBaseStudy(response.plot_data)
	},
	openEmptyWorkbookForDev() {
		if (!study.value?.plot_data) return
		study.value = createBaseStudy(study.value.plot_data)
		phase.value = 'ready'
		error.value = ''
	},
	async generateStudy() {
		const plot = selectedPlot.value
		if (!plot) return
		phase.value = 'generating'
		error.value = ''
		try {
			const next = await feasibility.generateStudy({
				plot_number: plot.plot_number,
				usage_override: study.value?.assumptions.usage
			})
			mergeStudy(next as unknown as Record<string, unknown>)
		} catch (err) {
			phase.value = 'error'
			error.value = err instanceof Error ? err.message : 'Failed to generate feasibility study.'
		}
	},
	reset() {
		phase.value = 'search'
		selectedPlot.value = null
		study.value = null
		error.value = ''
	}
}
