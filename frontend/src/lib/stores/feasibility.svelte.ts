import { nanoid } from 'nanoid';

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

// Central state
const step = $state({ value: 1 as 1 | 2 | 3 | 4 });
const area = $state({ value: null as string | null });
const plot = $state({ value: null as LandPlot | null });
const plotSizeInput = $state({ value: null as number | null });
const comparables = $state({ value: [] as ComparableProject[] });
const showSpreadsheet = $state({ value: false });
const config = $state<{ value: ProjectConfig }>({
	value: { buildings: [], pricePerSqm: {} }
});

// Derived
const totalUnits = $derived(
	config.value.buildings.reduce(
		(sum, b) => sum + b.units.reduce((s, u) => s + u.count, 0),
		0
	)
);

const totalSellableAreaSqm = $derived(
	config.value.buildings.reduce(
		(sum, b) => sum + b.units.reduce((s, u) => s + u.count * u.avgSizeSqm, 0),
		0
	)
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

const totalGDV = $derived(
	Object.values(gdvByType()).reduce((s, v) => s + v, 0)
);

const spreadsheetRows = $derived(() => {
	// Aggregate units by type across all buildings
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

// Actions
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

function applyComparableData(data: ComparableData) {
	// Build one building per comparable building count (cap at 3 for UX)
	const numBuildings = Math.min(data.no_of_buildings || 1, 3);
	const avgFloors = Math.round(data.avg_floors ?? 10);
	const buildings: BuildingConfig[] = Array.from({ length: numBuildings }, (_, i) => ({
		id: nanoid(),
		name: `Tower ${i + 1}`,
		floors: avgFloors,
		units: data.unit_mix.map((u) => ({
			type: u.type,
			count: Math.round(u.count / numBuildings),
			avgSizeSqm: u.avg_size_sqm,
		})),
	}));

	config.value = {
		buildings,
		pricePerSqm: { ...data.price_per_sqm_by_type },
	};
	step.value = 4;
	showSpreadsheet.value = true;
}

function addBuilding() {
	config.value.buildings = [
		...config.value.buildings,
		{
			id: nanoid(),
			name: `Tower ${config.value.buildings.length + 1}`,
			floors: 10,
			units: [],
		},
	];
}

function updateBuilding(id: string, patch: Partial<Omit<BuildingConfig, 'id'>>) {
	config.value.buildings = config.value.buildings.map((b) =>
		b.id === id ? { ...b, ...patch } : b
	);
}

function removeBuilding(id: string) {
	config.value.buildings = config.value.buildings.filter((b) => b.id !== id);
}

function setBuildings(buildings: BuildingConfig[]) {
	config.value.buildings = buildings;
}

function setUnitMix(unitMix: Record<string, UnitTypeCount[]>) {
	// unitMix keyed by building id
	config.value.buildings = config.value.buildings.map((b) =>
		unitMix[b.id] ? { ...b, units: unitMix[b.id] } : b
	);
}

function setPricePerSqm(prices: Record<string, number>) {
	config.value.pricePerSqm = { ...config.value.pricePerSqm, ...prices };
}

function applyLLMAction(action: string, payload: unknown) {
	if (action === 'set_buildings') setBuildings(payload as BuildingConfig[]);
	else if (action === 'set_unit_mix') setUnitMix(payload as Record<string, UnitTypeCount[]>);
	else if (action === 'set_price_per_sqm') setPricePerSqm(payload as Record<string, number>);
}

function goToStep(s: 1 | 2 | 3 | 4) {
	if (s <= step.value) step.value = s;
}

export const feasibilityStore = {
	get step() { return step.value; },
	get area() { return area.value; },
	get plot() { return plot.value; },
	get plotSizeInput() { return plotSizeInput.value; },
	get comparables() { return comparables.value; },
	get showSpreadsheet() { return showSpreadsheet.value; },
	get config() { return config.value; },
	get totalUnits() { return totalUnits; },
	get totalSellableAreaSqm() { return totalSellableAreaSqm; },
	get gdvByType() { return gdvByType(); },
	get totalGDV() { return totalGDV; },
	get spreadsheetRows() { return spreadsheetRows(); },
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
	applyLLMAction,
	goToStep,
	toggleSpreadsheet: () => { showSpreadsheet.value = !showSpreadsheet.value; },
};
