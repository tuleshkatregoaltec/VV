<script lang="ts">
	import { feasibilityStore, type BuildingConfig, type UnitTypeCount } from '$lib/stores/feasibility.svelte';
	import { nanoid } from 'nanoid';

	const UNIT_TYPES = ['Studio', '1BR', '2BR', '3BR', '4BR', 'Penthouse'];

	function fmt(n: number) {
		return n.toLocaleString('en-AE', { maximumFractionDigits: 0 });
	}

	function fmtM(n: number) {
		if (n >= 1_000_000) return `AED ${(n / 1_000_000).toFixed(1)}M`;
		if (n >= 1_000) return `AED ${(n / 1_000).toFixed(0)}K`;
		return `AED ${fmt(n)}`;
	}

	// Inline edit state
	let editingBuildingId = $state<string | null>(null);
	let editingField = $state<string | null>(null);
	let editValue = $state('');

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
		const units = building.units.map((u) =>
			u.type === type ? { ...u, avgSizeSqm: size } : u
		);
		feasibilityStore.updateBuilding(building.id, { units });
	}

	function defaultSize(type: string): number {
		const defaults: Record<string, number> = {
			Studio: 45,
			'1BR': 70,
			'2BR': 110,
			'3BR': 160,
			'4BR': 220,
			Penthouse: 350,
		};
		return defaults[type] ?? 80;
	}

	function addUnitType(building: BuildingConfig) {
		const used = new Set(building.units.map((u) => u.type));
		const next = UNIT_TYPES.find((t) => !used.has(t));
		if (!next) return;
		const units = [...building.units, { type: next, count: 10, avgSizeSqm: defaultSize(next) }];
		feasibilityStore.updateBuilding(building.id, { units });
	}
</script>

<div class="space-y-6">
	<!-- Summary bar -->
	<div class="flex flex-wrap gap-4 p-4 rounded-xl bg-slate-50 border border-slate-200">
		<div>
			<p class="text-xs text-slate-500">Total Units</p>
			<p class="text-lg font-bold text-slate-800">{fmt(feasibilityStore.totalUnits)}</p>
		</div>
		<div>
			<p class="text-xs text-slate-500">Sellable Area</p>
			<p class="text-lg font-bold text-slate-800">{fmt(feasibilityStore.totalSellableAreaSqm)} sqm</p>
		</div>
		<div>
			<p class="text-xs text-slate-500">Estimated GDV</p>
			<p class="text-lg font-bold text-teal-700">{fmtM(feasibilityStore.totalGDV)}</p>
		</div>
	</div>

	<!-- Building cards -->
	<div class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
		{#each feasibilityStore.config.buildings as building (building.id)}
			<div class="bg-white rounded-xl border border-slate-200 p-4 flex flex-col gap-3">
				<!-- Building header -->
				<div class="flex items-center justify-between">
					<div class="flex items-center gap-2 flex-1 min-w-0">
						{#if editingBuildingId === building.id && editingField === 'name'}
							<input
								type="text"
								class="text-sm font-semibold text-slate-800 bg-transparent border-b border-teal-400 outline-none w-full"
								bind:value={editValue}
								onblur={() => commitEdit(building)}
								onkeydown={(e) => { if (e.key === 'Enter') commitEdit(building); }}
								autofocus
							/>
						{:else}
							<button
								type="button"
								class="text-sm font-semibold text-slate-800 truncate hover:text-teal-600 text-left"
								onclick={() => startEdit(building.id, 'name', building.name)}
							>
								{building.name}
							</button>
						{/if}
					</div>
					<button
						type="button"
						class="text-slate-300 hover:text-red-400 transition-colors ml-2 flex-shrink-0"
						onclick={() => feasibilityStore.removeBuilding(building.id)}
						title="Remove building"
					>
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>

				<!-- Floors -->
				<div class="flex items-center gap-2 text-xs text-slate-500">
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16" />
					</svg>
					{#if editingBuildingId === building.id && editingField === 'floors'}
						<input
							type="number"
							class="w-12 border-b border-teal-400 outline-none text-slate-800 font-medium bg-transparent"
							bind:value={editValue}
							onblur={() => commitEdit(building)}
							onkeydown={(e) => { if (e.key === 'Enter') commitEdit(building); }}
							min="1"
							autofocus
						/>
						<span>floors</span>
					{:else}
						<button
							type="button"
							class="font-medium text-slate-700 hover:text-teal-600"
							onclick={() => startEdit(building.id, 'floors', building.floors)}
						>
							{building.floors} floors
						</button>
					{/if}
				</div>

				<!-- Unit types -->
				<div class="space-y-2">
					{#each building.units as unit}
						<div class="flex items-center gap-2">
							<span class="text-xs font-medium text-slate-600 w-16 flex-shrink-0">{unit.type}</span>
							<input
								type="number"
								class="w-14 px-2 py-1 text-xs rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-400"
								value={unit.count}
								min="0"
								oninput={(e) => updateUnitCount(building, unit.type, parseInt((e.target as HTMLInputElement).value) || 0)}
								title="Unit count"
							/>
							<span class="text-xs text-slate-400">×</span>
							<input
								type="number"
								class="w-16 px-2 py-1 text-xs rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-400"
								value={unit.avgSizeSqm}
								min="1"
								step="0.5"
								oninput={(e) => updateUnitSize(building, unit.type, parseFloat((e.target as HTMLInputElement).value) || 0)}
								title="Avg size sqm"
							/>
							<span class="text-xs text-slate-400">sqm</span>
						</div>
					{/each}
				</div>

				<button
					type="button"
					class="text-xs text-teal-600 hover:text-teal-700 font-medium text-left"
					onclick={() => addUnitType(building)}
				>
					+ Add unit type
				</button>
			</div>
		{/each}

		<!-- Add building card -->
		<button
			type="button"
			class="flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-slate-200 p-6 text-slate-400 hover:border-teal-400 hover:text-teal-500 transition-all min-h-[160px]"
			onclick={() => feasibilityStore.addBuilding()}
		>
			<svg class="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 4v16m8-8H4" />
			</svg>
			<span class="text-sm font-medium">Add Building</span>
		</button>
	</div>

	<!-- Price per sqm section -->
	<div class="bg-white rounded-xl border border-slate-200 p-4">
		<h3 class="text-sm font-semibold text-slate-700 mb-3">Price assumptions (AED/sqm)</h3>
		<div class="flex flex-wrap gap-3">
			{#each Object.entries(feasibilityStore.config.pricePerSqm) as [type, price]}
				<div class="flex items-center gap-1.5">
					<span class="text-xs font-medium text-slate-600 w-16">{type}</span>
					<input
						type="number"
						class="w-24 px-2 py-1 text-xs rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-400"
						value={price}
						min="0"
						step="100"
						oninput={(e) => {
							const v = parseFloat((e.target as HTMLInputElement).value);
							if (!isNaN(v)) feasibilityStore.setPricePerSqm({ [type]: v });
						}}
					/>
					<span class="text-xs text-slate-400">AED</span>
				</div>
			{/each}
		</div>
	</div>
</div>
