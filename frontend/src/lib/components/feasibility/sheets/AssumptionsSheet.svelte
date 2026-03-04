<script lang="ts">
	import { feasibilityStore, type BuildingConfig, type UnitTypeCount } from '$lib/stores/feasibility.svelte';

	const UNIT_TYPES = ['Studio', '1BR', '2BR', '3BR', '4BR', '5BR', 'Penthouse'];

	// --- Unit mix editor ---
	let editingBuildingId = $state<string | null>(null);
	let editingField = $state<string | null>(null);
	let editValue = $state('');
	let unitMixOpen = $state(true);

	function startEdit(buildingId: string, field: string, current: string | number) {
		editingBuildingId = buildingId;
		editingField = field;
		editValue = String(current);
	}

	function commitEdit(building: BuildingConfig) {
		if (!editingBuildingId || !editingField) return;
		if (editingField === 'name') {
			feasibilityStore.updateBuilding(building.id, { name: editValue });
		} else if (editingField === 'floors') {
			const v = parseInt(editValue);
			if (!isNaN(v) && v > 0) feasibilityStore.updateBuilding(building.id, { floors: v });
		}
		editingBuildingId = null;
		editingField = null;
	}

	function updateUnitCount(building: BuildingConfig, type: string, count: number) {
		const existing = building.units.find((u) => u.type === type);
		let units: UnitTypeCount[];
		if (count <= 0) {
			units = building.units.filter((u) => u.type !== type);
		} else if (existing) {
			units = building.units.map((u) => (u.type === type ? { ...u, count } : u));
		} else {
			units = [...building.units, { type, count, avgSizeSqm: defaultSize(type) }];
		}
		feasibilityStore.updateBuilding(building.id, { units });
	}

	function updateUnitSize(building: BuildingConfig, type: string, size: number) {
		feasibilityStore.updateBuilding(building.id, {
			units: building.units.map((u) => (u.type === type ? { ...u, avgSizeSqm: size } : u)),
		});
	}

	function addUnitType(building: BuildingConfig, type: string) {
		const units = [...building.units, { type, count: 10, avgSizeSqm: defaultSize(type) }];
		units.sort((a, b) => UNIT_TYPES.indexOf(a.type) - UNIT_TYPES.indexOf(b.type));
		feasibilityStore.updateBuilding(building.id, { units });
	}

	function defaultSize(type: string): number {
		const defaults: Record<string, number> = {
			Studio: 45, '1BR': 70, '2BR': 110, '3BR': 160, '4BR': 220, '5BR': 280, Penthouse: 350,
		};
		return defaults[type] ?? 80;
	}

	function fmt(n: number) { return n.toLocaleString('en-AE', { maximumFractionDigits: 0 }); }
	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string { return `${n.toFixed(1)}%`; }

	// --- Assumptions ---
	let open = $state<Record<string, boolean>>({
		land: true, construction: true, sales: true, financing: true, macro: true,
	});
	function toggle(key: string) { open[key] = !open[key]; }

	const a = $derived(feasibilityStore.assumptions);

	// Editable: yellow bg + dark blue text
	const inputClass =
		'w-full text-right px-2 py-1.5 bg-amber-50 focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal-400 tabular-nums text-blue-800 text-[11px]';

	// Unit mix inputs
	const unitInputClass =
		'w-full px-1.5 py-1 text-xs rounded border border-slate-200 bg-amber-50 text-blue-800 focus:outline-none focus:ring-1 focus:ring-teal-400 tabular-nums min-w-0';

	function numInput(key: keyof typeof a, e: Event) {
		const v = parseFloat((e.target as HTMLInputElement).value);
		if (!isNaN(v)) feasibilityStore.setAssumptions({ [key]: v });
	}
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>

	<!-- UNIT MIX -->
	<table class="w-full border-collapse">
		<tbody>
			<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => (unitMixOpen = !unitMixOpen)}>
				<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
					{unitMixOpen ? '▼' : '▶'} Unit Mix
				</td>
			</tr>
		</tbody>
	</table>
	{#if unitMixOpen}
		<div class="p-2 space-y-2 border-b-2 border-slate-200">
			<div class="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-slate-500 pb-0.5">
				<span class="font-semibold text-slate-700">{fmt(feasibilityStore.totalUnits)}</span> units ·
				<span class="font-semibold text-slate-700">{fmt(feasibilityStore.totalSellableAreaSqm)}</span> sqm ·
				<span class="font-semibold text-slate-700">{fmtK(feasibilityStore.totalGDV)}</span> GDV ('000)
			</div>

			{#each feasibilityStore.config.buildings as building (building.id)}
				{@const usedTypes = new Set(building.units.map((u) => u.type))}
				{@const availableTypes = UNIT_TYPES.filter((t) => !usedTypes.has(t))}
				<div class="bg-white rounded border border-slate-200 p-2.5 flex flex-col gap-2">
					<div class="flex items-center gap-2 min-w-0">
						<div class="flex-1 min-w-0">
							{#if editingBuildingId === building.id && editingField === 'name'}
								<input
									type="text"
									class="text-xs font-semibold text-slate-800 bg-transparent border-b border-teal-400 outline-none w-full"
									bind:value={editValue}
									onblur={() => commitEdit(building)}
									onkeydown={(e) => { if (e.key === 'Enter') commitEdit(building); }}
									autofocus
								/>
							{:else}
								<button type="button"
									class="text-xs font-semibold text-slate-700 hover:text-teal-600 text-left truncate w-full"
									onclick={() => startEdit(building.id, 'name', building.name)}
								>{building.name}</button>
							{/if}
						</div>
						<div class="flex items-center gap-1 text-[11px] text-slate-400 flex-shrink-0">
							<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16" />
							</svg>
							{#if editingBuildingId === building.id && editingField === 'floors'}
								<input type="number"
									class="w-9 border-b border-teal-400 outline-none text-blue-800 font-medium bg-transparent text-[11px] tabular-nums"
									bind:value={editValue}
									onblur={() => commitEdit(building)}
									onkeydown={(e) => { if (e.key === 'Enter') commitEdit(building); }}
									min="1" autofocus />
							{:else}
								<button type="button" class="font-medium text-slate-600 hover:text-teal-600"
									onclick={() => startEdit(building.id, 'floors', building.floors)}
								>{building.floors}F</button>
							{/if}
						</div>
						<button type="button" class="text-slate-300 hover:text-red-400 transition-colors flex-shrink-0"
							onclick={() => feasibilityStore.removeBuilding(building.id)} title="Remove building">
							<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
							</svg>
						</button>
					</div>

					<div class="space-y-1.5">
						{#each building.units as unit}
							<div class="grid items-center gap-x-1.5 min-w-0" style="grid-template-columns: 3rem 1fr auto 1fr auto auto">
								<span class="text-[11px] font-medium text-slate-500 truncate">{unit.type}</span>
								<input type="number" class={unitInputClass} value={unit.count} min="0" title="Count"
									oninput={(e) => updateUnitCount(building, unit.type, parseInt((e.target as HTMLInputElement).value) || 0)} />
								<span class="text-[11px] text-slate-300">×</span>
								<input type="number" class={unitInputClass} value={unit.avgSizeSqm} min="1" step="0.5" title="Avg sqm"
									oninput={(e) => updateUnitSize(building, unit.type, parseFloat((e.target as HTMLInputElement).value) || 0)} />
								<span class="text-[11px] text-slate-400">sqm</span>
								<button type="button" class="text-slate-200 hover:text-red-400 transition-colors"
									onclick={() => updateUnitCount(building, unit.type, 0)} title="Remove">
									<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
										<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" />
									</svg>
								</button>
							</div>
						{/each}
					</div>

					{#if availableTypes.length > 0}
						<div class="flex flex-wrap gap-1 pt-0.5">
							{#each availableTypes as type}
								<button type="button"
									class="text-[10px] px-1.5 py-0.5 rounded border border-dashed border-slate-200 text-slate-400 hover:border-teal-400 hover:text-teal-600 transition-colors"
									onclick={() => addUnitType(building, type)}>{type}</button>
							{/each}
						</div>
					{/if}
				</div>
			{/each}

			<button type="button"
				class="w-full py-1.5 text-xs font-medium text-slate-400 hover:text-teal-600 border border-dashed border-slate-200 hover:border-teal-400 rounded transition-colors"
				onclick={() => feasibilityStore.addBuilding()}>+ Add building</button>
		</div>
	{/if}

	<!-- ASSUMPTIONS TABLE -->
	<table class="w-full border-collapse">
		<tbody>

		<!-- LAND & SITE -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('land')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.land ? '▼' : '▶'} Land & Site
			</td>
		</tr>
		{#if open.land}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 w-56">Land Cost</td>
				<td class="border-r border-slate-200 p-0 w-28 relative">
					{#if feasibilityStore.changedFields['landCost']}
						<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
					{/if}
					<input type="number" class={inputClass} value={Math.round(a.landCost / 1000)} min="0" step="500"
						oninput={(e) => {
							const v = parseFloat((e.target as HTMLInputElement).value);
							if (!isNaN(v)) feasibilityStore.setAssumptions({ landCost: v * 1000 });
						}} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">AED '000</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">DLD Transfer Fee</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if feasibilityStore.changedFields['transferFeePct']}
						<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
					{/if}
					<input type="number" class={inputClass} value={a.transferFeePct} min="0" step="0.5" oninput={(e) => numInput('transferFeePct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">%</td>
			</tr>
		{/if}

		<!-- CONSTRUCTION -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('construction')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.construction ? '▼' : '▶'} Construction
			</td>
		</tr>
		{#if open.construction}
			{#each [
				{ label: 'Build Cost/sqm', key: 'buildCostPerSqm' as const, step: 50, unit: 'AED/sqm' },
				{ label: 'Contingency (% of hard)', key: 'contingencyPct' as const, step: 1, unit: '%' },
				{ label: 'Construction Period', key: 'constructionMonths' as const, step: 1, unit: 'months' },
				{ label: 'Soft Costs (% of hard)', key: 'softCostsPct' as const, step: 1, unit: '%' },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">{row.label}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.key]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						<input type="number" class={inputClass} value={a[row.key]} min="0" step={row.step} oninput={(e) => numInput(row.key, e)} />
					</td>
					<td class="px-2 py-1.5 text-slate-400">{row.unit}</td>
				</tr>
			{/each}
			{#each [
				{ label: '└ Design & Engineering', key: 'designFeePct' as const, step: 0.5 },
				{ label: '└ Project Management', key: 'projectMgmtPct' as const, step: 0.5 },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 pl-5 text-slate-500">{row.label}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.key]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						<input type="number" class={inputClass} value={a[row.key]} min="0" step={row.step} oninput={(e) => numInput(row.key, e)} />
					</td>
					<td class="px-2 py-1.5 text-slate-400">%</td>
				</tr>
			{/each}
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 pl-5 text-slate-400">└ Other Soft Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">
					{fmtPct(Math.max(0, a.softCostsPct - a.designFeePct - a.projectMgmtPct))}
				</td>
				<td class="px-2 py-1.5 text-slate-400">(derived)</td>
			</tr>
		{/if}

		<!-- SALES & MARKETING -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('sales')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.sales ? '▼' : '▶'} Sales & Marketing
			</td>
		</tr>
		{#if open.sales}
			{#each [
				{ label: 'Sales Launch (months)', key: 'salesLaunchMonth' as const, step: 1, unit: 'months' },
				{ label: 'Sales Duration (months)', key: 'salesMonths' as const, step: 1, unit: 'months' },
				{ label: 'Agent Commission', key: 'agentCommissionPct' as const, step: 0.5, unit: '%' },
				{ label: 'Marketing Budget', key: 'marketingBudgetPct' as const, step: 0.5, unit: '%' },
				{ label: 'Presale Discount', key: 'presaleDiscountPct' as const, step: 1, unit: '%' },
				{ label: 'Price Escalation p.a.', key: 'priceEscalationPct' as const, step: 0.5, unit: '%' },
				{ label: 'Post-handover Unsold', key: 'postHandoverSalesPct' as const, step: 5, unit: '%' },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">{row.label}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.key]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						<input type="number" class={inputClass} value={a[row.key]} min="0" step={row.step} oninput={(e) => numInput(row.key, e)} />
					</td>
					<td class="px-2 py-1.5 text-slate-400">{row.unit}</td>
				</tr>
			{/each}
		{/if}

		<!-- FINANCING -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('financing')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.financing ? '▼' : '▶'} Financing
			</td>
		</tr>
		{#if open.financing}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Debt-to-Cost Ratio</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if feasibilityStore.changedFields['debtToCostRatio']}
						<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
					{/if}
					<input type="number" class={inputClass}
						value={(a.debtToCostRatio * 100).toFixed(0)} min="0" max="100" step="1"
						oninput={(e) => {
							const v = parseFloat((e.target as HTMLInputElement).value);
							if (!isNaN(v)) feasibilityStore.setAssumptions({ debtToCostRatio: v / 100 });
						}} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">%</td>
			</tr>
			{#each [
				{ label: 'Interest Rate p.a.', key: 'financeRatePct' as const, step: 0.5, unit: '%' },
				{ label: 'Arrangement Fee', key: 'arrangementFeePct' as const, step: 0.25, unit: '%' },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">{row.label}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.key]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						<input type="number" class={inputClass} value={a[row.key]} min="0" step={row.step} oninput={(e) => numInput(row.key, e)} />
					</td>
					<td class="px-2 py-1.5 text-slate-400">{row.unit}</td>
				</tr>
			{/each}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">
					Interest-only Period
					{#if a.interestOnlyMonthsOverride === null}
						<span class="ml-1.5 text-[9px] px-1.5 py-0.5 bg-teal-100 text-teal-700 rounded font-medium">auto</span>
					{/if}
				</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if feasibilityStore.changedFields['interestOnlyMonthsOverride']}
						<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
					{/if}
					<input type="number" class={inputClass} value={feasibilityStore.interestOnlyMonths} min="0" step="1"
						oninput={(e) => {
							const v = parseFloat((e.target as HTMLInputElement).value);
							if (!isNaN(v)) feasibilityStore.setAssumptions({ interestOnlyMonthsOverride: v });
						}} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 flex items-center gap-1.5">
					months
					{#if a.interestOnlyMonthsOverride !== null}
						<button type="button"
							class="text-[9px] px-1.5 py-0.5 bg-slate-200 hover:bg-slate-300 text-slate-600 rounded transition-colors"
							onclick={() => feasibilityStore.setAssumptions({ interestOnlyMonthsOverride: null })}>reset</button>
					{/if}
				</td>
			</tr>
		{/if}

		<!-- MACRO -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('macro')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.macro ? '▼' : '▶'} Macro
			</td>
		</tr>
		{#if open.macro}
			{#each [
				{ label: 'Inflation / Cost Escalation', key: 'inflationPct' as const, step: 0.5, unit: '%' },
				{ label: 'Discount Rate', key: 'discountRatePct' as const, step: 0.5, unit: '%' },
				{ label: 'Rental Yield Assumption', key: 'rentalYieldPct' as const, step: 0.5, unit: '%' },
				{ label: 'Target ROC', key: 'targetROCPct' as const, step: 5, unit: '%' },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">{row.label}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.key]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						<input type="number" class={inputClass} value={a[row.key]} min="0" step={row.step} oninput={(e) => numInput(row.key, e)} />
					</td>
					<td class="px-2 py-1.5 text-slate-400">{row.unit}</td>
				</tr>
			{/each}
		{/if}

		</tbody>
	</table>
</div>
