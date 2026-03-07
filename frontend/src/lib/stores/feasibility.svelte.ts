import { SvelteSet } from 'svelte/reactivity';
import { nanoid } from 'nanoid';
import { researchPanelStore } from './researchPanel.svelte';

export interface UnitTypeCount {
	type: string;
	count: number;
	avgSizeSqm: number; // net sellable area (NSA) per unit in sqm
}

export interface BuildingConfig {
	id: string;
	name: string;
	phase: string; // e.g. "Tower A — Phase 1"
	floors: number;
	units: UnitTypeCount[];
}

export interface ProjectConfig {
	buildings: BuildingConfig[];
	pricePerSqm: Record<string, number>;
}

export interface EscrowMilestone {
	name: string;
	pct: number;            // % of pre-handover GDV collected at this milestone
	constructionPct: number; // % construction completion that triggers this (0 = booking/SPA)
}

const DEFAULT_ESCROW_MILESTONES: EscrowMilestone[] = [
	{ name: 'Booking + SPA', pct: 20, constructionPct: 0 },
	{ name: 'Foundation', pct: 10, constructionPct: 20 },
	{ name: '40% Complete', pct: 10, constructionPct: 40 },
	{ name: '60% Complete', pct: 10, constructionPct: 60 },
	{ name: '80% Complete', pct: 10, constructionPct: 80 },
	{ name: 'Handover', pct: 40, constructionPct: 100 },
];

export interface Assumptions {
	// Land
	landCost: number;
	transferFeePct: number;

	// Construction
	buildCostPerSqm: number;
	softCostsPct: number;
	contingencyPct: number;
	designFeePct: number;
	projectMgmtPct: number;
	constructionMonths: number;

	// Sales & Marketing
	salesLaunchMonth: number;
	salesMonths: number;
	agentCommissionPct: number;
	marketingBudgetPct: number;
	presaleDiscountPct: number;
	priceEscalationPct: number;
	postHandoverSalesPct: number;

	// Financing
	financeRatePct: number;
	debtToCostRatio: number;
	arrangementFeePct: number;
	interestOnlyMonthsOverride: number | null;

	// BUA
	buaEfficiencyPct: number;

	// Site & Areas (Phase 2)
	siteAreaSqm: number;       // total site / plot area
	plotRatioFAR: number;      // floor area ratio
	lossFactorGFAtoNSA: number; // % loss from GFA to NSA (default 15%)
	hasDemolition: boolean;
	hasAncillaryRetail: boolean;

	// Phase 3 — absolute cost line items
	infrastructureCostAED: number;
	authorityConnectionFeesAED: number;
	communityMasterDevFeesAED: number;
	demolitionCostAED: number;
	designSupervisionAED: number;
	projectMgmtAED: number;
	otherProfessionalFeesAED: number;
	marketingLaunchAED: number;
	midPointInflationPct: number;
	// VAT
	vatRateOnCostsPct: number;
	vatRecoveryPct: number;
	// Corporate tax
	corporateTaxRatePct: number;

	// Phase 4 — Escrow & Revenue Model
	useEscrowModel: boolean;
	escrowMilestones: EscrowMilestone[];
	offPlanProceedsUsedForConstructionPct: number;
	capexDistributionCurve: 'linear' | 'sCurve' | 'frontLoaded' | 'backLoaded';
	hasVATBridgeLoan: boolean;
	vatBridgeLoanTermMonths: number;
	vatBridgeLoanRatePct: number;
	// Retail income (active when hasAncillaryRetail)
	retailAreaSqm: number;
	retailRentPerSqmYr: number;
	retailYieldCapRate: number;

	// Macro
	discountRatePct: number;
	targetROCPct: number;

	// Programme
	projectStartDate: string | null;
}

export interface GISPlotSummary {
	plot_number: string;
	community_name: string;
	project_name: string;
	plot_area_sqm: number;
	max_gfa_sqm: number;
	max_height: string;
	max_coverage: string;
	gfa_type: string;
	is_verified: boolean;
	land_use_summary: string[];
}

export interface GISLandUse {
	type: string;
	use: string;
}

export interface GISPlotDossier {
	plot_number: string;
	community_name: string;
	project_name: string;
	master_developer: string | null;
	plot_area_sqm: number;
	max_gfa_sqm: number;
	max_gfa_sqft: number;
	max_height: string;
	max_coverage: string;
	gfa_type: string;
	far: number | null;
	inferred_usage: 'residential' | 'commercial' | 'mixed_use' | 'unknown';
	site_plan_issue_date: string | null;
	site_plan_expiry_date: string | null;
	is_verified: boolean;
	verify_comments: string | null;
	land_use: GISLandUse[];
	general_notes: string[];
	setbacks: Record<string, string>;
	coordinates: number[][];
	warnings: string[];
}

export interface ComparableProjectEvidence {
	project_id: number;
	project_name: string;
	area_name: string;
	project_status: string | null;
	comparison_type: 'pricing' | 'pipeline';
	score: number;
	total_land_area_sqm: number | null;
	land_area_delta_pct: number | null;
	no_of_buildings: number | null;
	no_of_units: number | null;
	median_price_sqm: number | null;
	dominant_unit_type: string | null;
	rationale: string[];
}

export interface MarketPricingRow {
	unit_type: string;
	transaction_count: number;
	median_price_sqm: number;
	avg_area_sqm: number | null;
}

export interface LandSaleEvidence {
	transaction_id: string;
	instance_date: string;
	area_name: string;
	project_name: string;
	procedure_name: string;
	property_usage: string;
	plot_area_sqm: number;
	price_aed: number;
	price_sqm: number;
	nearest_landmark: string | null;
}

export interface ComparableData {
	project_id: number;
	project_name: string;
	area_name: string;
	no_of_buildings: number;
	avg_floors: number | null;
	unit_mix: Array<{
		type: string;
		count: number;
		percentage: number;
		avg_size_sqm: number;
		avg_price_sqm: number | null;
	}>;
	price_per_sqm_by_type: Record<string, number>;
}

export interface HBUProductOption {
	name: string;
	positioning: string;
	fit_score: number;
	rationale: string[];
}

export interface HBUUnitRecommendation {
	unit_type: string;
	share_pct: number;
	avg_size_sqm: number;
	price_sqm: number;
	suggested_units: number;
}

export interface HBUStudy {
	plot_number: string;
	usage: 'residential' | 'commercial' | 'mixed_use' | 'unknown';
	market_area: string;
	headline: string;
	summary: string[];
	constraints: string[];
	pricing_evidence: ComparableProjectEvidence[];
	competition_evidence: ComparableProjectEvidence[];
	land_sales_evidence: LandSaleEvidence[];
	market_pricing: MarketPricingRow[];
	product_options: HBUProductOption[];
	recommended_mix: HBUUnitRecommendation[];
	price_per_sqm_by_type: Record<string, number>;
	assumptions_patch: Record<string, string | number | boolean>;
	warnings: string[];
}

function quarterlyIRR(cfs: number[]): number {
	if (!cfs.some((c) => c > 0) || !cfs.some((c) => c < 0)) return NaN;
	let r = 0.05;
	for (let i = 0; i < 100; i++) {
		const npv = cfs.reduce((s, cf, t) => s + cf / (1 + r) ** t, 0);
		const dnpv = cfs.reduce((s, cf, t) => s - (t * cf) / (1 + r) ** (t + 1), 0);
		if (Math.abs(dnpv) < 1e-10) break;
		const next = r - npv / dnpv;
		if (Math.abs(next - r) < 1e-6) {
			r = next;
			break;
		}
		r = next;
	}
	return (1 + r) ** 4 - 1;
}

// Central state
const step = $state({ value: 1 as 1 | 2 | 3 | 4 });
const area = $state({ value: null as string | null });
const plot = $state({ value: null as GISPlotSummary | null });
const plotDossier = $state({ value: null as GISPlotDossier | null });
const hbuStudy = $state({ value: null as HBUStudy | null });
const plotSizeInput = $state({ value: null as number | null });
const showSpreadsheet = $state({ value: false });
const assumptions = $state<{ value: Assumptions }>({
	value: {
		landCost: 0,
		transferFeePct: 4,
		buildCostPerSqm: 2000,
		softCostsPct: 15,
		contingencyPct: 5,
		designFeePct: 3,
		projectMgmtPct: 2,
		buaEfficiencyPct: 80,
		siteAreaSqm: 0,
		plotRatioFAR: 0,
		lossFactorGFAtoNSA: 15,
		hasDemolition: false,
		hasAncillaryRetail: false,
		infrastructureCostAED: 0,
		authorityConnectionFeesAED: 0,
		communityMasterDevFeesAED: 0,
		demolitionCostAED: 0,
		designSupervisionAED: 0,
		projectMgmtAED: 0,
		otherProfessionalFeesAED: 0,
		marketingLaunchAED: 0,
		midPointInflationPct: 0,
		vatRateOnCostsPct: 5,
		vatRecoveryPct: 100,
		corporateTaxRatePct: 9,
		useEscrowModel: false,
		escrowMilestones: DEFAULT_ESCROW_MILESTONES,
		offPlanProceedsUsedForConstructionPct: 100,
		capexDistributionCurve: 'linear',
		hasVATBridgeLoan: false,
		vatBridgeLoanTermMonths: 12,
		vatBridgeLoanRatePct: 7,
		retailAreaSqm: 0,
		retailRentPerSqmYr: 0,
		retailYieldCapRate: 8,
		constructionMonths: 24,
		salesLaunchMonth: 6,
		salesMonths: 18,
		agentCommissionPct: 2,
		marketingBudgetPct: 1,
		presaleDiscountPct: 5,
		priceEscalationPct: 3,
		postHandoverSalesPct: 10,
		financeRatePct: 7,
		debtToCostRatio: 0.65,
		arrangementFeePct: 1.5,
		interestOnlyMonthsOverride: null,
		discountRatePct: 10,
		targetROCPct: 20,
		projectStartDate: null,
	},
});

// ── Display currency state ─────────────────────────────────────────────────────
const displayCurrency = $state({ value: 'AED' as 'AED' | 'USD' });
const fxRateAEDtoUSD = $state({ value: 3.6725 });
const config = $state<{ value: ProjectConfig }>({
	value: { buildings: [], pricePerSqm: {} },
});

// ── UX state: agent-change feedback ───────────────────────────────────────────
// changedFields: key → counter (non-zero = recently changed, counter lets animation re-trigger)
const changedFields = $state({ value: {} as Record<string, number> });
// undoFields: same pattern but triggers red flash on undo
const undoFields = $state({ value: {} as Record<string, number> });
// affectedTabs: set of tab ids that have unseen agent changes
const affectedTabs = $state({ value: new SvelteSet<string>() });
// undoSnapshot: taken before each batch of agent actions
const undoSnapshot = $state<{
	value: { assumptions: Assumptions; pricePerSqm: Record<string, number>; buildings: BuildingConfig[] } | null;
}>({ value: null });
// lastChangedKeys: keys changed in the last agent batch, used for undo flash
const lastChangedKeys = $state({ value: [] as string[] });

// ── Unit config derived ────────────────────────────────────────────────────────

const totalUnits = $derived(
	config.value.buildings.reduce((sum, b) => sum + b.units.reduce((s, u) => s + u.count, 0), 0),
);

const totalSellableAreaSqm = $derived(
	config.value.buildings.reduce(
		(sum, b) => sum + b.units.reduce((s, u) => s + u.count * u.avgSizeSqm, 0),
		0,
	),
);

const gdvByType = $derived(() => {
	const result: Record<string, number> = {};
	for (const building of config.value.buildings) {
		for (const unit of building.units) {
			const price = config.value.pricePerSqm[unit.type] ?? 0;
			result[unit.type] = (result[unit.type] ?? 0) + unit.count * unit.avgSizeSqm * price;
		}
	}
	return result;
});

const totalGDV = $derived(Object.values(gdvByType()).reduce((s, v) => s + v, 0));

const spreadsheetRows = $derived(() => {
	const byType: Record<string, { count: number; totalArea: number }> = {};
	for (const building of config.value.buildings) {
		for (const unit of building.units) {
			if (!byType[unit.type]) byType[unit.type] = { count: 0, totalArea: 0 };
			byType[unit.type].count += unit.count;
			byType[unit.type].totalArea += unit.count * unit.avgSizeSqm;
		}
	}
	return Object.entries(byType).map(([type, data]) => ({
		type,
		count: data.count,
		avgSizeSqm: data.count > 0 ? data.totalArea / data.count : 0,
		pricePerSqm: config.value.pricePerSqm[type] ?? 0,
		totalProceeds: data.totalArea * (config.value.pricePerSqm[type] ?? 0),
	}));
});

const totalBUA = $derived(
	assumptions.value.buaEfficiencyPct > 0
		? totalSellableAreaSqm / (assumptions.value.buaEfficiencyPct / 100)
		: totalSellableAreaSqm,
);

// Area model (Phase 2) — GFA/GSA/NSA chain
// maxGFA: from site parameters (informational — does not drive cost model in Phase 2)
const maxGFA = $derived(assumptions.value.siteAreaSqm * assumptions.value.plotRatioFAR);
// totalGSA: gross sellable area derived from unit NSA sizes and loss factor
const totalGSA = $derived(
	assumptions.value.lossFactorGFAtoNSA < 100
		? totalSellableAreaSqm / (1 - assumptions.value.lossFactorGFAtoNSA / 100)
		: totalSellableAreaSqm,
);

// ── Financial derived (dependency order) ──────────────────────────────────────

// interestOnlyMonths: auto-shadows constructionMonths unless overridden
const interestOnlyMonths = $derived(
	assumptions.value.interestOnlyMonthsOverride ?? assumptions.value.constructionMonths,
);

// Land
const transferFees = $derived((assumptions.value.landCost * assumptions.value.transferFeePct) / 100);
const totalLandCost = $derived(assumptions.value.landCost + transferFees);

// Hard construction
const hardCost = $derived(totalBUA * assumptions.value.buildCostPerSqm);
const contingencyCost = $derived((hardCost * assumptions.value.contingencyPct) / 100);
const totalHardCost = $derived(hardCost + contingencyCost);

// Phase 3: absolute cost line items
const totalInfrastructureCost = $derived(
	assumptions.value.infrastructureCostAED +
	assumptions.value.authorityConnectionFeesAED +
	assumptions.value.communityMasterDevFeesAED +
	(assumptions.value.hasDemolition ? assumptions.value.demolitionCostAED : 0)
);
const totalProfessionalFees = $derived(
	assumptions.value.designSupervisionAED +
	assumptions.value.projectMgmtAED +
	assumptions.value.otherProfessionalFeesAED
);
const absoluteSoftCostTotal = $derived(totalInfrastructureCost + totalProfessionalFees);
const totalSoftCost = $derived(absoluteSoftCostTotal);

// Sales & marketing
const agentFees = $derived((totalGDV * assumptions.value.agentCommissionPct) / 100);
const marketingCost = $derived((totalGDV * assumptions.value.marketingBudgetPct) / 100);
const totalSalesCost = $derived(agentFees + marketingCost + assumptions.value.marketingLaunchAED);
const netRevenue = $derived(totalGDV - totalSalesCost);

// Pre/post handover revenue split
const postHandoverUnits = $derived(
	Math.round((totalUnits * assumptions.value.postHandoverSalesPct) / 100),
);
const preHandoverUnits = $derived(totalUnits - postHandoverUnits);
const preHandoverGDV = $derived(
	totalGDV *
		(preHandoverUnits / Math.max(1, totalUnits)) *
		(1 - assumptions.value.presaleDiscountPct / 100),
);
const postHandoverGDV = $derived(totalGDV * (postHandoverUnits / Math.max(1, totalUnits)));
const totalBlendedGDV = $derived(preHandoverGDV + postHandoverGDV);

// Price escalation
const priceEscalationMultiplier = $derived(
	(1 + assumptions.value.priceEscalationPct / 100) ** (assumptions.value.salesMonths / 24),
);
const escalatedGDV = $derived(totalGDV * priceEscalationMultiplier);

// Mid-point inflation on construction + soft costs
const inflationOnCosts = $derived(
	assumptions.value.midPointInflationPct > 0
		? (totalHardCost + totalSoftCost) *
		  ((1 + assumptions.value.midPointInflationPct / 100) ** (assumptions.value.constructionMonths / 24) - 1)
		: 0
);

// Pre-finance subtotal (debtAmount must not include finance costs to avoid circularity)
const preFinanceCost = $derived(totalLandCost + totalHardCost + totalSoftCost + inflationOnCosts + totalSalesCost);

// Finance
const debtAmount = $derived(preFinanceCost * assumptions.value.debtToCostRatio);
const equityRequired = $derived(preFinanceCost * (1 - assumptions.value.debtToCostRatio));
const arrangementFee = $derived((debtAmount * assumptions.value.arrangementFeePct) / 100);
const totalInterest = $derived(
	(debtAmount * assumptions.value.financeRatePct * interestOnlyMonths) / (100 * 12),
);
const totalFinanceCost = $derived(totalInterest + arrangementFee);

// Project totals
const totalDevCost = $derived(preFinanceCost + totalFinanceCost);
const grossProfit = $derived(totalGDV - totalDevCost);
const returnOnCost = $derived(totalDevCost > 0 ? (grossProfit / totalDevCost) * 100 : 0);
const returnOnEquity = $derived(equityRequired > 0 ? (grossProfit / equityRequired) * 100 : 0);
const equityMultiple = $derived(
	equityRequired > 0 ? (equityRequired + grossProfit) / equityRequired : 0,
);

// VAT (memo only — typically fully recoverable by registered UAE developers)
const vatOnCosts = $derived(
	(totalHardCost + totalSoftCost + inflationOnCosts) * (assumptions.value.vatRateOnCostsPct / 100)
);
const vatRecovery = $derived(vatOnCosts * (assumptions.value.vatRecoveryPct / 100));
const netVATPosition = $derived(vatOnCosts - vatRecovery);

// Corporate tax (9% UAE CT; applied to gross profit, shown as deduction)
const corporateTaxProvision = $derived(
	Math.max(0, grossProfit * (assumptions.value.corporateTaxRatePct / 100))
);
const netProfit = $derived(grossProfit - corporateTaxProvision);

const blendedPricePerSqm = $derived(totalSellableAreaSqm > 0 ? totalGDV / totalSellableAreaSqm : 0);

// Retail income (Phase 4)
const retailAnnualIncome = $derived(
	assumptions.value.hasAncillaryRetail && assumptions.value.retailAreaSqm > 0
		? assumptions.value.retailAreaSqm * assumptions.value.retailRentPerSqmYr
		: 0,
);
const retailCapValue = $derived(
	retailAnnualIncome > 0 && assumptions.value.retailYieldCapRate > 0
		? retailAnnualIncome / (assumptions.value.retailYieldCapRate / 100)
		: 0,
);

// VAT bridge loan (Phase 4)
const vatBridgeLoanInterest = $derived(
	assumptions.value.hasVATBridgeLoan
		? vatOnCosts * (assumptions.value.vatBridgeLoanRatePct / 100) * (assumptions.value.vatBridgeLoanTermMonths / 12)
		: 0,
);

// ── Cashflow model ─────────────────────────────────────────────────────────────

const cq = $derived(Math.ceil(assumptions.value.constructionMonths / 3));
const sq = $derived(Math.ceil(assumptions.value.salesLaunchMonth / 3));
const nq = $derived(Math.ceil(assumptions.value.salesMonths / 3));
const totalQ = $derived(Math.max(cq, sq + nq));

// Capex distribution weights normalized to sum = 1 (Phase 4)
const capexWeights = $derived(
	(() => {
		if (cq === 0) return [] as number[];
		const curve = assumptions.value.capexDistributionCurve;
		const weights = Array.from({ length: cq }, (_, q) => {
			const third = cq / 3;
			if (curve === 'sCurve') {
				if (q < third) return 0.25 / (cq / 3);
				if (q < 2 * third) return 0.50 / (cq / 3);
				return 0.25 / (cq / 3);
			}
			if (curve === 'frontLoaded') {
				if (q < third) return 0.50 / (cq / 3);
				if (q < 2 * third) return 0.35 / (cq / 3);
				return 0.15 / (cq / 3);
			}
			if (curve === 'backLoaded') {
				if (q < third) return 0.15 / (cq / 3);
				if (q < 2 * third) return 0.35 / (cq / 3);
				return 0.50 / (cq / 3);
			}
			return 1 / cq; // linear
		});
		const sum = weights.reduce((s, w) => s + w, 0);
		return sum > 0 ? weights.map(w => w / sum) : weights;
	})(),
);

// Escrow receipts/releases per quarter (Phase 4)
const escrowData = $derived(
	(() => {
		const receipts = Array(totalQ).fill(0) as number[];
		const releases = Array(totalQ).fill(0) as number[];
		if (assumptions.value.useEscrowModel && totalQ > 0 && cq > 0) {
			const releasePct = assumptions.value.offPlanProceedsUsedForConstructionPct / 100;
			for (const m of assumptions.value.escrowMilestones) {
				const qIdx = m.constructionPct === 0
					? Math.max(0, sq)
					: Math.min(Math.floor((m.constructionPct / 100) * cq), totalQ - 1);
				const amount = (m.pct / 100) * preHandoverGDV;
				if (qIdx >= 0 && qIdx < totalQ) {
					receipts[qIdx] += amount;
					releases[qIdx] += amount * releasePct;
				}
			}
			// Post-handover GDV released at handover
			const handoverQ = Math.min(cq, totalQ - 1);
			receipts[handoverQ] += postHandoverGDV;
			releases[handoverQ] += postHandoverGDV;
		}
		let cumFloat = 0;
		return Array.from({ length: totalQ }, (_, q) => {
			cumFloat += receipts[q] - releases[q];
			return { q, receipt: receipts[q], release: releases[q], float: cumFloat };
		});
	})(),
);

const cashflow = $derived(
	(() => {
		let cum = 0;
		const escPct = assumptions.value.priceEscalationPct / 100;
		const useEscrow = assumptions.value.useEscrowModel;
		return Array.from({ length: totalQ }, (_, q) => {
			const land = q === 0 ? assumptions.value.landCost : 0;
			const w = q < cq ? (capexWeights[q] ?? 0) : 0;
			const construction = totalHardCost * w;
			const soft = totalSoftCost * w;
			const marketing = q >= sq && q < sq + nq ? totalSalesCost / nq : 0;
			const costs = land + construction + soft + marketing;
			let revenue: number;
			if (useEscrow) {
				revenue = escrowData[q]?.release ?? 0;
			} else {
				// Apply price escalation quarterly: later sales quarters earn higher revenue
				const escalation = q >= sq && q < sq + nq ? Math.pow(1 + escPct, (q - sq) / 4) : 1;
				const preRev = q >= sq && q < sq + nq ? (preHandoverGDV / nq) * escalation : 0;
				const postRev = q === cq ? postHandoverGDV : 0;
				revenue = preRev + postRev;
			}
			const net = revenue - costs;
			cum += net;
			return { q, land, construction, soft, marketing, costs, revenue, net, cum };
		});
	})(),
);

const peakFunding = $derived(Math.abs(Math.min(0, ...cashflow.map((p) => p.cum))));
const cashBreakevenQuarter = $derived(cashflow.findIndex((p) => p.cum >= 0));

// IRR (annualised from quarterly rate)
const unleveredIRR = $derived(quarterlyIRR(cashflow.map((p) => p.revenue - p.costs)));

// Levered cash flows (shared by leveredIRR and npvLevered)
const leveredCashFlows = $derived((() => {
	if (cq === 0) return null;
	const quarterlyRate = assumptions.value.financeRatePct / 100 / 4;
	const equityRatio = 1 - assumptions.value.debtToCostRatio;
	const cfs = cashflow.map((p) => {
		const interest = p.q < cq ? debtAmount * quarterlyRate : 0;
		return p.revenue - p.costs * equityRatio - interest;
	});
	if (cfs.length > cq) cfs[cq] = (cfs[cq] ?? 0) - debtAmount;
	return cfs;
})());

const leveredIRR = $derived(leveredCashFlows ? quarterlyIRR(leveredCashFlows) : NaN);

// ── Additional derived (Phase 1) ───────────────────────────────────────────────

function calculateNPV(cashFlows: number[], quarterlyRate: number): number {
	return cashFlows.reduce((npv, cf, t) => npv + cf / (1 + quarterlyRate) ** t, 0);
}

const leveredProfit = $derived(netRevenue - debtAmount - totalInterest);
const profitOnGDVPct = $derived(totalGDV > 0 ? (grossProfit / totalGDV) * 100 : 0);

const npvUnlevered = $derived(
	calculateNPV(
		cashflow.map((p) => p.revenue - p.costs),
		assumptions.value.discountRatePct / 100 / 4,
	),
);

const npvLevered = $derived(
	leveredCashFlows
		? calculateNPV(leveredCashFlows, assumptions.value.discountRatePct / 100 / 4)
		: NaN,
);

// Scenario snapshots: scale cashflow revenues/costs by multipliers
function computeScenario(priceM: number, costM: number): { roc: number; unleveredIRR: number } {
	const adjGDV = totalGDV * priceM;
	const adjDevCost = totalDevCost * costM;
	const roc = adjDevCost > 0 ? ((adjGDV - adjDevCost) / adjDevCost) * 100 : 0;
	const cfs = cashflow.map((p) => p.revenue * priceM - p.costs * costM);
	const irr = quarterlyIRR(cfs);
	return { roc, unleveredIRR: isNaN(irr) ? NaN : irr };
}

const stressScenario = $derived(computeScenario(0.9, 1.1));
const baseScenario = $derived(computeScenario(1.0, 1.0));
const upsideScenario = $derived(computeScenario(1.1, 0.95));

// ── Actions ────────────────────────────────────────────────────────────────────

function setArea(v: string) {
	area.value = v;
}

function setPlot(v: GISPlotSummary) {
	plot.value = v;
	area.value = v.community_name;
	plotDossier.value = null;
	hbuStudy.value = null;
	if (v.plot_area_sqm > 0) {
		assumptions.value = { ...assumptions.value, siteAreaSqm: v.plot_area_sqm };
	}
	step.value = 2;
}

// Normalize DLD-style names ("1 B/R", "2 B/R") to clean short form ("1BR", "2BR")
function normalizeUnitType(type: string): string {
	if (type === 'studio') return 'Studio';
	if (/^\dbr\+$/.test(type.toLowerCase())) return '4BR+';
	return type
		.replace(/^(\d+)\s*B\/R$/i, '$1BR')
		.replace(/^(\d)br$/i, (_, n) => `${n}BR`)
		.replace(/townhouse/gi, 'Townhouse')
		.replace(/villa/gi, 'Villa')
		.replace(/office/gi, 'Office')
		.replace(/retail/gi, 'Retail');
}

function setPlotDossier(dossier: GISPlotDossier) {
	plotDossier.value = dossier;
	area.value = dossier.community_name;
	const patch: Partial<Assumptions> = { siteAreaSqm: dossier.plot_area_sqm };
	if (dossier.far && dossier.far > 0) patch.plotRatioFAR = dossier.far;
	assumptions.value = { ...assumptions.value, ...patch };
	step.value = 2;
}

function estimateStudyGDV(study: HBUStudy) {
	return study.recommended_mix.reduce(
		(sum, row) => sum + row.suggested_units * row.avg_size_sqm * row.price_sqm,
		0,
	);
}

function conservativeSeedAssumptions(study: HBUStudy, dossier: GISPlotDossier | null): Partial<Assumptions> {
	const estimatedGDV = estimateStudyGDV(study);
	const usage = study.usage;
	const buildCostFloor =
		usage === 'commercial' ? 4500 : usage === 'mixed_use' ? 4250 : 3500;
	const landRatio =
		usage === 'commercial' ? 0.28 : usage === 'mixed_use' ? 0.3 : 0.25;

	return {
		siteAreaSqm: dossier?.plot_area_sqm ?? assumptions.value.siteAreaSqm,
		plotRatioFAR: dossier?.far && dossier.far > 0 ? dossier.far : assumptions.value.plotRatioFAR,
		lossFactorGFAtoNSA: Math.max(
			Number(study.assumptions_patch.lossFactorGFAtoNSA ?? assumptions.value.lossFactorGFAtoNSA ?? 15),
			15,
		),
		buildCostPerSqm: Math.max(
			Number(study.assumptions_patch.buildCostPerSqm ?? assumptions.value.buildCostPerSqm ?? 0),
			buildCostFloor,
		),
		contingencyPct: Math.max(
			Number(study.assumptions_patch.contingencyPct ?? assumptions.value.contingencyPct ?? 0),
			7,
		),
		constructionMonths: Math.max(
			Number(study.assumptions_patch.constructionMonths ?? assumptions.value.constructionMonths ?? 0),
			30,
		),
		salesMonths: Math.max(
			Number(study.assumptions_patch.salesMonths ?? assumptions.value.salesMonths ?? 0),
			24,
		),
		landCost:
			assumptions.value.landCost > 0
				? assumptions.value.landCost
				: Math.round(estimatedGDV * landRatio),
	};
}

function applyComparableData(data: ComparableData) {
	const numBuildings = Math.min(data.no_of_buildings || 1, 3);
	const avgFloors = Math.round(data.avg_floors ?? 10);
	const buildings: BuildingConfig[] = Array.from({ length: numBuildings }, (_, i) => ({
		id: nanoid(),
		name: `Tower ${i + 1}`,
		phase: '',
		floors: avgFloors,
		units: data.unit_mix.map((u) => ({
			type: normalizeUnitType(u.type),
			count: Math.round(u.count / numBuildings),
			avgSizeSqm: u.avg_size_sqm,
		})),
	}));
	const pricePerSqm = Object.fromEntries(
		Object.entries(data.price_per_sqm_by_type).map(([k, v]) => [normalizeUnitType(k), v]),
	);
	config.value = { buildings, pricePerSqm };
	researchPanelStore.setComparableMarketPrices(pricePerSqm);
	step.value = 4;
	showSpreadsheet.value = true;
}

function applyHBUStudy(study: HBUStudy) {
	hbuStudy.value = study;
	const buildings: BuildingConfig[] = [{
		id: nanoid(),
		name: study.product_options[0]?.name || 'HBU Scheme',
		phase: 'Phase 1',
		floors: Math.max(1, Math.round((plotDossier.value?.far ?? 0) * 4) || 10),
		units: study.recommended_mix.map((row) => ({
			type: normalizeUnitType(row.unit_type),
			count: row.suggested_units,
			avgSizeSqm: row.avg_size_sqm,
		})),
	}];
	const pricePerSqm = Object.fromEntries(
		Object.entries(study.price_per_sqm_by_type).map(([key, value]) => [normalizeUnitType(key), value]),
	);
	const assumptionsPatch = {
		...study.assumptions_patch,
		...conservativeSeedAssumptions(study, plotDossier.value),
	} as Partial<Assumptions>;
	config.value = { buildings, pricePerSqm };
	researchPanelStore.setComparableMarketPrices(pricePerSqm);
	assumptions.value = { ...assumptions.value, ...assumptionsPatch };
	researchPanelStore.setComparableEvidence({
		pricing: study.pricing_evidence,
		pipeline: study.competition_evidence,
		marketPricing: study.market_pricing,
	});
	researchPanelStore.setActiveTab('comparables');
	step.value = 4;
	showSpreadsheet.value = true;
}

function addBuilding() {
	const n = config.value.buildings.length + 1;
	config.value.buildings = [
		...config.value.buildings,
		{ id: nanoid(), name: `Tower ${n}`, phase: '', floors: 10, units: [] },
	];
}

function updateBuilding(id: string, patch: Partial<Omit<BuildingConfig, 'id'>>) {
	config.value.buildings = config.value.buildings.map((b) =>
		b.id === id ? { ...b, ...patch } : b,
	);
}

function removeBuilding(id: string) {
	config.value.buildings = config.value.buildings.filter((b) => b.id !== id);
}

function setBuildings(buildings: BuildingConfig[]) {
	config.value.buildings = buildings;
}

function setUnitMix(unitMix: Record<string, UnitTypeCount[]>) {
	config.value.buildings = config.value.buildings.map((b) =>
		unitMix[b.id] ? { ...b, units: unitMix[b.id] } : b,
	);
}

function setPricePerSqm(prices: Record<string, number>) {
	config.value.pricePerSqm = { ...config.value.pricePerSqm, ...prices };
}

function flashField(key: string, undo = false) {
	const target = undo ? undoFields : changedFields;
	target.value = { ...target.value, [key]: (target.value[key] ?? 0) + 1 };
	setTimeout(() => {
		const rest = { ...target.value };
		delete rest[key];
		target.value = rest;
	}, 1600);
}

// Keys that have direct inputs in DevBudget (in addition to Assumptions)
const DEVBUDGET_KEYS = new Set([
	'landCost', 'transferFeePct', 'buaEfficiencyPct', 'buildCostPerSqm', 'contingencyPct',
	'softCostsPct', 'designFeePct', 'projectMgmtPct',
	'agentCommissionPct', 'marketingBudgetPct', 'financeRatePct', 'arrangementFeePct',
	// Phase 3 — absolute line items
	'infrastructureCostAED', 'authorityConnectionFeesAED', 'communityMasterDevFeesAED',
	'demolitionCostAED', 'designSupervisionAED', 'projectMgmtAED', 'otherProfessionalFeesAED',
	'marketingLaunchAED', 'midPointInflationPct', 'vatRateOnCostsPct', 'vatRecoveryPct',
	'corporateTaxRatePct',
	// Phase 4
	'hasVATBridgeLoan', 'vatBridgeLoanTermMonths', 'vatBridgeLoanRatePct',
]);

function markTabsAffected(action: string, patch?: Record<string, unknown>) {
	const tabs = new SvelteSet(affectedTabs.value);
	tabs.add('summary'); // summary metrics change on any mutation
	if (action === 'set_price_per_sqm') {
		tabs.add('revenue');
	} else if (action === 'set_assumptions' && patch) {
		for (const key of Object.keys(patch)) {
			tabs.add('assumptions');
			if (DEVBUDGET_KEYS.has(key)) tabs.add('devbudget');
		}
	} else if (action === 'set_buildings' || action === 'set_unit_mix') {
		tabs.add('revenue');
	}
	affectedTabs.value = tabs;
}

function takeUndoSnapshot() {
	undoSnapshot.value = {
		assumptions: { ...assumptions.value },
		pricePerSqm: { ...config.value.pricePerSqm },
		buildings: config.value.buildings.map((b) => ({ ...b, units: [...b.units] })),
	};
}

function undoLastChange() {
	if (!undoSnapshot.value) return;
	assumptions.value = undoSnapshot.value.assumptions;
	config.value.pricePerSqm = undoSnapshot.value.pricePerSqm;
	config.value.buildings = undoSnapshot.value.buildings;
	undoSnapshot.value = null;
	for (const key of lastChangedKeys.value) flashField(key, true);
	lastChangedKeys.value = [];
	changedFields.value = {};
	affectedTabs.value = new SvelteSet();
}

function clearAffectedTab(tabId: string) {
	const tabs = new SvelteSet(affectedTabs.value);
	tabs.delete(tabId);
	affectedTabs.value = tabs;
}

function applyLLMAction(action: string, payload: unknown) {
	if (action === 'set_buildings') {
		setBuildings(payload as BuildingConfig[]);
		markTabsAffected(action);
	} else if (action === 'set_unit_mix') {
		setUnitMix(payload as Record<string, UnitTypeCount[]>);
		markTabsAffected(action);
	} else if (action === 'set_price_per_sqm') {
		const prices = payload as Record<string, number>;
		const keys = Object.keys(prices);
		for (const key of keys) flashField(key);
		setPricePerSqm(prices);
		markTabsAffected(action);
		lastChangedKeys.value = [...lastChangedKeys.value, ...keys];
	} else if (action === 'set_assumptions') {
		const patch = { ...(payload as Record<string, unknown>) };
		// Backward-compat: split sellingCostsPct 2:1 into agent:marketing
		if ('sellingCostsPct' in patch) {
			const v = patch.sellingCostsPct as number;
			patch.agentCommissionPct = +(v * (2 / 3)).toFixed(2);
			patch.marketingBudgetPct = +(v * (1 / 3)).toFixed(2);
			delete patch.sellingCostsPct;
		}
		const keys = Object.keys(patch);
		for (const key of keys) flashField(key);
		assumptions.value = { ...assumptions.value, ...(patch as Partial<Assumptions>) };
		markTabsAffected(action, patch);
		lastChangedKeys.value = [...lastChangedKeys.value, ...keys];
	}
}

function goToStep(s: 1 | 2 | 3 | 4) {
	if (s === 1) {
		step.value = 1;
		return;
	}
	if (s === 2 && plotDossier.value) {
		step.value = 2;
		return;
	}
	if (s === 3 && plotDossier.value) {
		step.value = 3;
		return;
	}
	if (s === 4 && hbuStudy.value) {
		step.value = 4;
	}
}

function devJump() {
	area.value = 'Business Bay';
	plot.value = {
		plot_number: 'BB-001',
		community_name: 'Business Bay',
		project_name: '',
		plot_area_sqm: 5000,
		max_gfa_sqm: 17500,
		max_height: 'G+25',
		max_coverage: '65%',
		gfa_type: 'Residential',
		is_verified: true,
		land_use_summary: ['RESIDENTIAL: APARTMENTS'],
	};
	plotDossier.value = {
		plot_number: 'BB-001',
		community_name: 'Business Bay',
		project_name: '',
		master_developer: null,
		plot_area_sqm: 5000,
		max_gfa_sqm: 17500,
		max_gfa_sqft: 188362,
		max_height: 'G+25',
		max_coverage: '65%',
		gfa_type: 'Residential',
		far: 3.5,
		inferred_usage: 'residential',
		site_plan_issue_date: null,
		site_plan_expiry_date: null,
		is_verified: true,
		verify_comments: null,
		land_use: [{ type: 'RESIDENTIAL', use: 'APARTMENTS' }],
		general_notes: [],
		setbacks: {},
		coordinates: [],
		warnings: [],
	};
	assumptions.value = { ...assumptions.value, landCost: 50_000_000, siteAreaSqm: 5000, plotRatioFAR: 3.5 };
	applyHBUStudy({
		plot_number: 'BB-001',
		usage: 'residential',
		market_area: 'Business Bay',
		headline: 'Initial HBU: luxury residential apartments on plot BB-001',
		summary: ['Luxury residential is the best initial fit.', 'Studios should stay limited.'],
		constraints: ['Plot area 5,000 sqm.', 'Maximum GFA 17,500 sqm.', 'Maximum height G+25.'],
		pricing_evidence: [],
		competition_evidence: [],
		market_pricing: [],
		product_options: [{ name: 'Luxury residential', positioning: 'High-end apartments with limited studios', fit_score: 91, rationale: [] }],
		recommended_mix: [
			{ unit_type: '1br', share_pct: 30, avg_size_sqm: 82, price_sqm: 22000, suggested_units: 48 },
			{ unit_type: '2br', share_pct: 35, avg_size_sqm: 128, price_sqm: 20000, suggested_units: 39 },
			{ unit_type: '3br', share_pct: 20, avg_size_sqm: 182, price_sqm: 18500, suggested_units: 17 },
			{ unit_type: 'studio', share_pct: 15, avg_size_sqm: 48, price_sqm: 24500, suggested_units: 51 },
		],
		price_per_sqm_by_type: { '1br': 22000, '2br': 20000, '3br': 18500, studio: 24500 },
		assumptions_patch: { siteAreaSqm: 5000, plotRatioFAR: 3.5, lossFactorGFAtoNSA: 15, buaEfficiencyPct: 82 },
		warnings: [],
	});
}

export const feasibilityStore = {
	get step() { return step.value; },
	get area() { return area.value; },
	get plot() { return plot.value; },
	get plotDossier() { return plotDossier.value; },
	get hbuStudy() { return hbuStudy.value; },
	get plotSizeInput() { return plotSizeInput.value; },
	get showSpreadsheet() { return showSpreadsheet.value; },
	get config() { return config.value; },
	get assumptions() { return assumptions.value; },
	// Display currency
	get displayCurrency() { return displayCurrency.value; },
	get fxRateAEDtoUSD() { return fxRateAEDtoUSD.value; },
	// Unit config
	get totalUnits() { return totalUnits; },
	get totalSellableAreaSqm() { return totalSellableAreaSqm; },
	get totalBUA() { return totalBUA; },
	get maxGFA() { return maxGFA; },
	get totalGSA() { return totalGSA; },
	get gdvByType() { return gdvByType(); },
	get totalGDV() { return totalGDV; },
	get spreadsheetRows() { return spreadsheetRows(); },
	// Financial derived
	get interestOnlyMonths() { return interestOnlyMonths; },
	get transferFees() { return transferFees; },
	get totalLandCost() { return totalLandCost; },
	get hardCost() { return hardCost; },
	get contingencyCost() { return contingencyCost; },
	get totalHardCost() { return totalHardCost; },
	get designCost() { return designCost; },
	get projectMgmtCost() { return projectMgmtCost; },
	get otherSoftCost() { return otherSoftCost; },
	get totalInfrastructureCost() { return totalInfrastructureCost; },
	get totalProfessionalFees() { return totalProfessionalFees; },
	get absoluteSoftCostTotal() { return absoluteSoftCostTotal; },
	get totalSoftCost() { return totalSoftCost; },
	get agentFees() { return agentFees; },
	get marketingCost() { return marketingCost; },
	get totalSalesCost() { return totalSalesCost; },
	get netRevenue() { return netRevenue; },
	get postHandoverUnits() { return postHandoverUnits; },
	get preHandoverUnits() { return preHandoverUnits; },
	get preHandoverGDV() { return preHandoverGDV; },
	get postHandoverGDV() { return postHandoverGDV; },
	get totalBlendedGDV() { return totalBlendedGDV; },
	get priceEscalationMultiplier() { return priceEscalationMultiplier; },
	get escalatedGDV() { return escalatedGDV; },
	get inflationOnCosts() { return inflationOnCosts; },
	get preFinanceCost() { return preFinanceCost; },
	get debtAmount() { return debtAmount; },
	get equityRequired() { return equityRequired; },
	get arrangementFee() { return arrangementFee; },
	get totalInterest() { return totalInterest; },
	get totalFinanceCost() { return totalFinanceCost; },
	get totalDevCost() { return totalDevCost; },
	get grossProfit() { return grossProfit; },
	get returnOnCost() { return returnOnCost; },
	get returnOnEquity() { return returnOnEquity; },
	get equityMultiple() { return equityMultiple; },
	get vatOnCosts() { return vatOnCosts; },
	get vatRecovery() { return vatRecovery; },
	get netVATPosition() { return netVATPosition; },
	get corporateTaxProvision() { return corporateTaxProvision; },
	get netProfit() { return netProfit; },
	get blendedPricePerSqm() { return blendedPricePerSqm; },
	// Phase 4
	get retailAnnualIncome() { return retailAnnualIncome; },
	get retailCapValue() { return retailCapValue; },
	get vatBridgeLoanInterest() { return vatBridgeLoanInterest; },
	get capexWeights() { return capexWeights; },
	get escrowData() { return escrowData; },
	// Phase 1 additions
	get leveredProfit() { return leveredProfit; },
	get profitOnCostPct() { return returnOnCost; },
	get profitOnGDVPct() { return profitOnGDVPct; },
	get npvUnlevered() { return npvUnlevered; },
	get npvLevered() { return npvLevered; },
	get stressScenario() { return stressScenario; },
	get baseScenario() { return baseScenario; },
	get upsideScenario() { return upsideScenario; },
	computeScenario,
	// Cashflow
	get cq() { return cq; },
	get sq() { return sq; },
	get nq() { return nq; },
	get totalQ() { return totalQ; },
	get cashflow() { return cashflow; },
	get peakFunding() { return peakFunding; },
	get cashBreakevenQuarter() { return cashBreakevenQuarter; },
	get unleveredIRR() { return unleveredIRR; },
	get leveredIRR() { return leveredIRR; },
	// UX feedback
	get changedFields() { return changedFields.value; },
	get undoFields() { return undoFields.value; },
	get affectedTabs() { return affectedTabs.value; },
	get canUndo() { return undoSnapshot.value !== null; },
	// Actions
	setArea,
	setPlot,
	setPlotDossier,
	setPlotSizeInput: (v: number | null) => { plotSizeInput.value = v; },
	applyComparableData,
	applyHBUStudy,
	addBuilding,
	updateBuilding,
	removeBuilding,
	setBuildings,
	setUnitMix,
	setPricePerSqm,
	takeUndoSnapshot,
	undoLastChange,
	clearAffectedTab,
	applyLLMAction,
	goToStep,
	devJump,
	toggleSpreadsheet: () => { showSpreadsheet.value = !showSpreadsheet.value; },
	setAssumptions: (patch: Partial<Assumptions>) => {
		assumptions.value = { ...assumptions.value, ...patch };
	},
	setEscrowMilestone: (idx: number, patch: Partial<EscrowMilestone>) => {
		const milestones = assumptions.value.escrowMilestones.map((m, i) =>
			i === idx ? { ...m, ...patch } : m,
		);
		assumptions.value = { ...assumptions.value, escrowMilestones: milestones };
	},
	resetEscrowMilestones: () => {
		assumptions.value = { ...assumptions.value, escrowMilestones: DEFAULT_ESCROW_MILESTONES };
	},
	setDisplayCurrency: (c: 'AED' | 'USD') => { displayCurrency.value = c; },
	setFxRate: (rate: number) => { fxRateAEDtoUSD.value = rate; },
};
