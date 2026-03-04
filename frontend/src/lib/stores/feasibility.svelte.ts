import { nanoid } from 'nanoid';
import { researchPanelStore } from './researchPanel.svelte';

export interface UnitTypeCount {
	type: string;
	count: number;
	avgSizeSqm: number;
}

export interface BuildingConfig {
	id: string;
	name: string;
	floors: number;
	units: UnitTypeCount[];
}

export interface ProjectConfig {
	buildings: BuildingConfig[];
	pricePerSqm: Record<string, number>;
}

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

	// Macro
	inflationPct: number;
	discountRatePct: number;
	rentalYieldPct: number;
	targetROCPct: number;
}

export interface LandPlot {
	property_id: number;
	land_number: string | null;
	area_name_en: string;
	actual_area: number;
	property_type_en: string | null;
	is_free_hold: boolean | null;
	project_name_en: string | null;
}

export interface ComparableProject {
	project_id: number;
	name: string;
	area_name: string;
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
const plot = $state({ value: null as LandPlot | null });
const plotSizeInput = $state({ value: null as number | null });
const comparables = $state({ value: [] as ComparableProject[] });
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
		inflationPct: 2.5,
		discountRatePct: 10,
		rentalYieldPct: 6,
		targetROCPct: 20,
	},
});
const config = $state<{ value: ProjectConfig }>({
	value: { buildings: [], pricePerSqm: {} },
});
const rentalRatesPerSqm = $state({ value: {} as Record<string, number> });

// ── UX state: agent-change feedback ───────────────────────────────────────────
// changedFields: key → counter (non-zero = recently changed, counter lets animation re-trigger)
const changedFields = $state({ value: {} as Record<string, number> });
// undoFields: same pattern but triggers red flash on undo
const undoFields = $state({ value: {} as Record<string, number> });
// affectedTabs: set of tab ids that have unseen agent changes
const affectedTabs = $state({ value: new Set<string>() });
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

// ── Financial derived (dependency order) ──────────────────────────────────────

// interestOnlyMonths: auto-shadows constructionMonths unless overridden
const interestOnlyMonths = $derived(
	assumptions.value.interestOnlyMonthsOverride ?? assumptions.value.constructionMonths,
);

// Land
const transferFees = $derived((assumptions.value.landCost * assumptions.value.transferFeePct) / 100);
const totalLandCost = $derived(assumptions.value.landCost + transferFees);

// Hard construction
const hardCost = $derived(totalSellableAreaSqm * assumptions.value.buildCostPerSqm);
const contingencyCost = $derived((hardCost * assumptions.value.contingencyPct) / 100);
const totalHardCost = $derived(hardCost + contingencyCost);

// Soft costs (designFeePct + projectMgmtPct are sub-lines within softCostsPct total)
const designCost = $derived((totalHardCost * assumptions.value.designFeePct) / 100);
const projectMgmtCost = $derived((totalHardCost * assumptions.value.projectMgmtPct) / 100);
const otherSoftCost = $derived(
	(totalHardCost *
		Math.max(
			0,
			assumptions.value.softCostsPct -
				assumptions.value.designFeePct -
				assumptions.value.projectMgmtPct,
		)) /
		100,
);
const totalSoftCost = $derived((totalHardCost * assumptions.value.softCostsPct) / 100);

// Sales & marketing
const agentFees = $derived((totalGDV * assumptions.value.agentCommissionPct) / 100);
const marketingCost = $derived((totalGDV * assumptions.value.marketingBudgetPct) / 100);
const totalSalesCost = $derived(agentFees + marketingCost);
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

// Pre-finance subtotal (debtAmount must not include finance costs to avoid circularity)
const preFinanceCost = $derived(totalLandCost + totalHardCost + totalSoftCost + totalSalesCost);

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
const blendedPricePerSqm = $derived(totalSellableAreaSqm > 0 ? totalGDV / totalSellableAreaSqm : 0);

// ── Cashflow model ─────────────────────────────────────────────────────────────

const cq = $derived(Math.ceil(assumptions.value.constructionMonths / 3));
const sq = $derived(Math.ceil(assumptions.value.salesLaunchMonth / 3));
const nq = $derived(Math.ceil(assumptions.value.salesMonths / 3));
const totalQ = $derived(Math.max(cq, sq + nq));

const cashflow = $derived(
	(() => {
		let cum = 0;
		return Array.from({ length: totalQ }, (_, q) => {
			const land = q === 0 ? assumptions.value.landCost : 0;
			const construction = q < cq ? totalHardCost / cq : 0;
			const soft = q < cq ? totalSoftCost / cq : 0;
			const marketing = q >= sq && q < sq + nq ? totalSalesCost / nq : 0;
			const costs = land + construction + soft + marketing;
			const preRev = q >= sq && q < sq + nq ? preHandoverGDV / nq : 0;
			const postRev = q === cq ? postHandoverGDV : 0;
			const revenue = preRev + postRev;
			const net = revenue - costs;
			cum += net;
			return { q, land, construction, soft, marketing, costs, revenue, net, cum };
		});
	})(),
);

const peakFunding = $derived(Math.abs(Math.min(0, ...cashflow.map((p) => p.cum))));
const cashBreakevenQuarter = $derived(cashflow.findIndex((p) => p.cum >= 0));

// IRR (annualised from quarterly rate)
const unleveredIRR = $derived(
	(() => {
		const cfs = cashflow.map((p) => p.revenue - p.costs);
		return quarterlyIRR(cfs);
	})(),
);

const leveredIRR = $derived(
	(() => {
		if (cq === 0) return NaN;
		const quarterlyRate = assumptions.value.financeRatePct / 100 / 4;
		const equityRatio = 1 - assumptions.value.debtToCostRatio;
		const cfs = cashflow.map((p) => {
			const equityCosts = p.costs * equityRatio;
			const interest = p.q < cq ? debtAmount * quarterlyRate : 0;
			return p.revenue - equityCosts - interest;
		});
		if (cfs.length > cq) cfs[cq] = (cfs[cq] ?? 0) - debtAmount;
		return quarterlyIRR(cfs);
	})(),
);

// ── Actions ────────────────────────────────────────────────────────────────────

function setArea(v: string) {
	area.value = v;
	step.value = 2;
}

function setPlot(v: LandPlot) {
	plot.value = v;
	step.value = 3;
}

function setComparables(projects: ComparableProject[]) {
	comparables.value = projects;
}

// Normalize DLD-style names ("1 B/R", "2 B/R") to clean short form ("1BR", "2BR")
function normalizeUnitType(type: string): string {
	return type.replace(/^(\d+)\s*B\/R$/i, '$1BR');
}

function applyComparableData(data: ComparableData) {
	const numBuildings = Math.min(data.no_of_buildings || 1, 3);
	const avgFloors = Math.round(data.avg_floors ?? 10);
	const buildings: BuildingConfig[] = Array.from({ length: numBuildings }, (_, i) => ({
		id: nanoid(),
		name: `Tower ${i + 1}`,
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

function addBuilding() {
	config.value.buildings = [
		...config.value.buildings,
		{ id: nanoid(), name: `Tower ${config.value.buildings.length + 1}`, floors: 10, units: [] },
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

function setRentalRate(type: string, ratePerSqmYr: number) {
	rentalRatesPerSqm.value = { ...rentalRatesPerSqm.value, [type]: ratePerSqmYr };
}

function flashField(key: string) {
	changedFields.value = { ...changedFields.value, [key]: (changedFields.value[key] ?? 0) + 1 };
	setTimeout(() => {
		const { [key]: _, ...rest } = changedFields.value;
		changedFields.value = rest;
	}, 1600);
}

function flashFieldUndo(key: string) {
	undoFields.value = { ...undoFields.value, [key]: (undoFields.value[key] ?? 0) + 1 };
	setTimeout(() => {
		const { [key]: _, ...rest } = undoFields.value;
		undoFields.value = rest;
	}, 1600);
}

// Keys that have direct inputs in DevBudget (in addition to Assumptions)
const DEVBUDGET_KEYS = new Set([
	'landCost', 'transferFeePct', 'buildCostPerSqm', 'contingencyPct',
	'softCostsPct', 'designFeePct', 'projectMgmtPct',
	'agentCommissionPct', 'marketingBudgetPct', 'financeRatePct', 'arrangementFeePct',
]);

function markTabsAffected(action: string, patch?: Record<string, unknown>) {
	const tabs = new Set(affectedTabs.value);
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
	for (const key of lastChangedKeys.value) flashFieldUndo(key);
	lastChangedKeys.value = [];
	changedFields.value = {};
	affectedTabs.value = new Set();
}

function clearAffectedTab(tabId: string) {
	const tabs = new Set(affectedTabs.value);
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
	if (s <= step.value) step.value = s;
}

function devJump() {
	area.value = 'Business Bay';
	plot.value = {
		property_id: 1,
		land_number: 'BB-001',
		area_name_en: 'Business Bay',
		actual_area: 5000,
		property_type_en: 'Land',
		is_free_hold: true,
		project_name_en: null,
	};
	assumptions.value = { ...assumptions.value, landCost: 50_000_000 };
	applyComparableData({
		project_id: 1,
		project_name: 'Test Tower',
		area_name: 'Business Bay',
		no_of_buildings: 1,
		avg_floors: 15,
		unit_mix: [
			{ type: 'Studio', count: 20, percentage: 25, avg_size_sqm: 45, avg_price_sqm: 28000 },
			{ type: '1 B/R', count: 30, percentage: 37.5, avg_size_sqm: 75, avg_price_sqm: 22000 },
			{ type: '2 B/R', count: 20, percentage: 25, avg_size_sqm: 120, avg_price_sqm: 20000 },
			{ type: '3 B/R', count: 10, percentage: 12.5, avg_size_sqm: 180, avg_price_sqm: 18000 },
		],
		price_per_sqm_by_type: { Studio: 28000, '1 B/R': 22000, '2 B/R': 20000, '3 B/R': 18000 },
	});
}

export const feasibilityStore = {
	get step() { return step.value; },
	get area() { return area.value; },
	get plot() { return plot.value; },
	get plotSizeInput() { return plotSizeInput.value; },
	get comparables() { return comparables.value; },
	get showSpreadsheet() { return showSpreadsheet.value; },
	get config() { return config.value; },
	get assumptions() { return assumptions.value; },
	get rentalRatesPerSqm() { return rentalRatesPerSqm.value; },
	// Unit config
	get totalUnits() { return totalUnits; },
	get totalSellableAreaSqm() { return totalSellableAreaSqm; },
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
	get blendedPricePerSqm() { return blendedPricePerSqm; },
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
	setPlotSizeInput: (v: number | null) => { plotSizeInput.value = v; },
	setComparables,
	applyComparableData,
	addBuilding,
	updateBuilding,
	removeBuilding,
	setBuildings,
	setUnitMix,
	setPricePerSqm,
	setRentalRate,
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
};
