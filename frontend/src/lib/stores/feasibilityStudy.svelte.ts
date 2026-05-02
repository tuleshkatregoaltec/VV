import { feasibility } from '$lib/api/feasibility'
import type { Plot } from '$lib/api/generated/hey-api/types.gen'
import type {
	DevelopmentModel,
	FeasibilityAssumptions,
	FeasibilityStudy,
	UsageType,
	VatApplicability
} from '$lib/feasibility/workbook/models'

type StudyPhase = 'search' | 'generating' | 'ready' | 'error'
export interface DevelopmentModelOption {
	id: DevelopmentModel
	label: string
	descriptor: string
	description: string
	available: boolean
}

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

function defaultDevelopmentModel(usage: UsageType): DevelopmentModel | undefined {
	return usage === 'residential' || usage === 'mixed_use' ? 'build_to_sell_residential' : undefined
}

function developmentModelOptions(usage: UsageType): DevelopmentModelOption[] {
	if (usage === 'residential') {
		return [
			{
				id: 'build_to_sell_residential',
				label: 'Build to sell',
				descriptor: 'Residential',
				description: 'For-sale residential underwriting. This is the active generation path today.',
				available: true
			},
			{
				id: 'build_to_rent_residential',
				label: 'Build to rent',
				descriptor: 'Residential',
				description:
					'Held rental residential product with operating P&L, exit valuation, and permanent debt sizing.',
				available: true
			}
		]
	}

	if (usage === 'mixed_use') {
		return [
			{
				id: 'build_to_sell_residential',
				label: 'Build to sell',
				descriptor: 'Residential',
				description: 'For-sale residential stack inside the mixed-use zoning envelope.',
				available: true
			},
			{
				id: 'build_to_rent_residential',
				label: 'Build to rent',
				descriptor: 'Residential',
				description:
					'Held rental residential product with operating P&L, exit valuation, and permanent debt sizing.',
				available: true
			},
			{
				id: 'build_to_lease_commercial',
				label: 'Build to lease',
				descriptor: 'Commercial',
				description:
					'Commercial lease-up path for the mixed-use commercial component. Visible in UX only for now.',
				available: false
			}
		]
	}

	return []
}

function defaultVatApplicability(): VatApplicability {
	return {
		land: true,
		hardCosts: true,
		softCosts: true,
		permitFees: true,
		contingency: true,
		marketing: true,
		salesAdmin: true
	}
}

function createBaseAssumptions(
	plot_data: NonNullable<FeasibilityStudy['plot_data']>
): FeasibilityAssumptions {
	const usage = plot_data.inferred_usage ?? 'unknown'

	return {
		// usage seeded from plot inference; user/agent can override
		usage,

		// Plot / area — seeded from plot data
		plotAreaSqm: plot_data.plot_area_sqm,
		maxGfaSqm: plot_data.max_gfa_sqm ?? 0,
		maxCoveragePct: parseMaxCoverage(plot_data.max_coverage),
		maxStoreys: parseMaxStoreys(plot_data.max_height),
		maxFar: plot_data.far ?? 0,
		plotNumber: plot_data.plot_number,
		communityName: plot_data.community_name,
		projectName: plot_data.project_name,
		gfaType: plot_data.gfa_type,
		sitePlanIssueDate: plot_data.site_plan_issue_date,
		sitePlanExpiryDate: plot_data.site_plan_expiry_date,
		plotWarnings: [...(plot_data.warnings ?? [])],
		numberOfTowers: 1,
		numberOfFloors: 1,
		buaMultiplier: 1.1,
		nsaEfficiencyPct: 80,

		// Unit mix
		unitConfigs: [],
		paymentPlan: { depositPct: 10, constructionPct: 30, handoverPct: 60 },

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
		debtToCostRatio: 0.7,
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

		// Schedule
		landAcquisitionDate: todayIsoDate(),
		demolitionEnablingDate: todayIsoDate(),
		salesCommencementDate: todayIsoDate(),
		salesPeriodMonths: 24,
		constructionDate: todayIsoDate(),
		handoverDate: todayIsoDate(),
		preHandoverMilestoneDate: todayIsoDate(),

		// Template-aligned workbook fields
		basementParkingFloors: 4,
		podiumFloors: 5,
		residentialFloors: 30,
		amenityRoofFloors: 1,
		parkingAreaPerSpaceSqm: 30,
		aboveGradeBuaFactor: 1.1,
		serviceBohPlantPct: 0.03,
		podiumParkingFloorsOutsideGfa: 0,
		landTransferFeePct: 0.04,
		brokeragePct: 0.01,
		legalDdPct: 0.005,
		permitFeesPct: 0.02,
		softCostPct: 0.15,
		acquisitionDebtLtv: 0.7,
		constructionDebtLtc: 0.7,
		debtSpreadPa: 0.02,
		financingFeePct: 0.01,
		exitFeePct: 0.01,
		preferredReturnPa: 0.08,
		sponsorPromotePct: 0.2,
		projectYears: 5,
		constructionCurveSteepness: 8,
		salesCurveSteepness: 8,
		vatAppliesTo: defaultVatApplicability(),
		vatRefundLagMonths: 6,
		selectedScenario: 'base',
		developmentModel: defaultDevelopmentModel(usage)
	}
}

function normalizeFinancingFields(assumptions: FeasibilityAssumptions): FeasibilityAssumptions {
	const acquisitionDebtLtv = assumptions.acquisitionDebtLtv ?? assumptions.landLoanLtvPct / 100
	const debtSpreadPa =
		assumptions.debtSpreadPa ??
		(assumptions.constructionLoanSpreadBps > 0
			? assumptions.constructionLoanSpreadBps / 10_000
			: assumptions.landLoanSpreadBps / 10_000)

	return {
		...assumptions,
		acquisitionDebtLtv,
		landLoanLtvPct: Math.round(acquisitionDebtLtv * 100),
		debtSpreadPa,
		landLoanSpreadBps: Math.round(debtSpreadPa * 10_000),
		constructionLoanSpreadBps: Math.round(debtSpreadPa * 10_000)
	}
}

function hydrateAssumptions(
	rawAssumptions: Partial<FeasibilityAssumptions> | undefined,
	plot_data: NonNullable<FeasibilityStudy['plot_data']>,
	research?: FeasibilityStudy['research'],
	selectedDevelopmentModel?: DevelopmentModel
): FeasibilityAssumptions {
	const base = createBaseAssumptions(plot_data)
	const merged: FeasibilityAssumptions = {
		...base,
		...(rawAssumptions ?? {}),
		paymentPlan: {
			...base.paymentPlan,
			...(rawAssumptions?.paymentPlan ?? {})
		},
		vatAppliesTo: {
			...base.vatAppliesTo,
			...(rawAssumptions?.vatAppliesTo ?? {})
		} as VatApplicability,
		unitConfigs: rawAssumptions?.unitConfigs ?? base.unitConfigs,
		plotNumber: plot_data.plot_number,
		communityName: plot_data.community_name,
		projectName: plot_data.project_name,
		gfaType: plot_data.gfa_type,
		sitePlanIssueDate: plot_data.site_plan_issue_date,
		sitePlanExpiryDate: plot_data.site_plan_expiry_date,
		plotWarnings: [...(plot_data.warnings ?? [])],
		developmentModel:
			rawAssumptions?.developmentModel ??
			selectedDevelopmentModel ??
			defaultDevelopmentModel(rawAssumptions?.usage ?? base.usage)
	}

	const normalized = normalizeFinancingFields(merged)
	const lowLandCost = research?.land_cost_estimate_aed_low ?? null
	const midLandCost = research?.land_cost_estimate_aed_mid ?? null
	const currentLandCost =
		normalized.landAcquisitionCostOverrideAed ??
		(normalized.plotAreaSqm > 0 ? normalized.plotAreaSqm * normalized.landPricePsqm : 0)

	if (midLandCost && lowLandCost && currentLandCost > 0 && currentLandCost < lowLandCost) {
		return {
			...normalized,
			landAcquisitionCostOverrideAed: midLandCost,
			landPricePsqm: normalized.plotAreaSqm > 0 ? midLandCost / normalized.plotAreaSqm : 0
		}
	}

	return normalized
}

function createBaseStudy(plot_data: NonNullable<FeasibilityStudy['plot_data']>): FeasibilityStudy {
	const assumptions = createBaseAssumptions(plot_data)

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
		rental_market_summary: null,
		rental_comparables: [],
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

function adaptBackendStudy(
	raw: Record<string, unknown>,
	selectedDevelopmentModel?: DevelopmentModel
): FeasibilityStudy {
	const plot_data = raw.plot_data as FeasibilityStudy['plot_data']
	const research = raw.research as FeasibilityStudy['research']
	const study_context = raw.study_context as FeasibilityStudy['study_context']
	const assumptions = hydrateAssumptions(
		raw.assumptions as Partial<FeasibilityAssumptions>,
		plot_data,
		research,
		selectedDevelopmentModel
	)
	return {
		status: 'ready',
		plot_data,
		assumptions: selectedDevelopmentModel
			? { ...assumptions, developmentModel: selectedDevelopmentModel }
			: assumptions,
		study_context,
		research,
		chat: (raw.chat as FeasibilityStudy['chat']) ?? { history: [] }
	}
}

function mergeStudy(raw: Record<string, unknown>, selectedDevelopmentModel?: DevelopmentModel) {
	study.value = adaptBackendStudy(raw, selectedDevelopmentModel)
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
	get developmentModelOptions() {
		const usage =
			study.value?.assumptions.usage ?? study.value?.plot_data.inferred_usage ?? 'unknown'
		return developmentModelOptions(usage)
	},
	get developmentModel() {
		return study.value?.assumptions.developmentModel
	},
	get developmentModelSelectorVisible() {
		const usage =
			study.value?.assumptions.usage ?? study.value?.plot_data.inferred_usage ?? 'unknown'
		return developmentModelOptions(usage).length > 0
	},
	get canGenerateSelectedModel() {
		const usage =
			study.value?.assumptions.usage ?? study.value?.plot_data.inferred_usage ?? 'unknown'
		const options = developmentModelOptions(usage)
		if (options.length === 0) return true
		const current = study.value?.assumptions.developmentModel
		if (!current) return false
		return options.some((option) => option.id === current && option.available)
	},
	get developmentModelMessage() {
		const usage =
			study.value?.assumptions.usage ?? study.value?.plot_data.inferred_usage ?? 'unknown'
		const options = developmentModelOptions(usage)
		if (options.length === 0) return ''
		if (!study.value?.assumptions.developmentModel) {
			return 'Select the intended development model before generation.'
		}
		const current = study.value.assumptions.developmentModel
		const canGenerate = options.some((option) => option.id === current && option.available)
		if (!canGenerate) {
			return 'This model type is not yet available. Select an active model to proceed.'
		}
		const modelLabel = options.find((o) => o.id === current)?.label ?? current
		return `${modelLabel} model is active and ready for generation.`
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
		const usage =
			study.value?.assumptions.usage ?? study.value?.plot_data.inferred_usage ?? 'unknown'
		const options = developmentModelOptions(usage)
		const current = study.value?.assumptions.developmentModel
		const canGenerate =
			options.length === 0 ||
			!!(current && options.some((option) => option.id === current && option.available))
		if (!canGenerate) {
			error.value =
				'This development model is not yet available. Select an active model to proceed.'
			return
		}
		phase.value = 'generating'
		error.value = ''
		try {
			const next = await feasibility.generateStudy({
				plot_number: plot.plot_number,
				usage_override: study.value?.assumptions.usage,
				development_model: current
			})
			mergeStudy(next as unknown as Record<string, unknown>, current)
		} catch (err) {
			phase.value = 'error'
			error.value = err instanceof Error ? err.message : 'Failed to generate feasibility study.'
		}
	},
	setDevelopmentModel(model: DevelopmentModel) {
		if (!study.value) return
		study.value = {
			...study.value,
			assumptions: {
				...study.value.assumptions,
				developmentModel: model
			}
		}
	},
	reset() {
		phase.value = 'search'
		selectedPlot.value = null
		study.value = null
		error.value = ''
	}
}
