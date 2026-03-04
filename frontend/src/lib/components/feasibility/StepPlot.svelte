<script lang="ts">
	import { feasibility } from '$lib/api/feasibility';
	import type { LandPlot } from '$lib/stores/feasibility.svelte';

	let {
		area,
		onSelect,
	}: {
		area: string;
		onSelect: (plot: LandPlot) => void;
	} = $props();

	let mode: 'search' | 'size' = $state('search');
	let searchInput = $state('');
	let sizeInput = $state('');
	let plots = $state<LandPlot[]>([]);
	let loading = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout>;

	function fmt(n: number) {
		return n.toLocaleString('en-AE', { maximumFractionDigits: 0 });
	}

	async function fetchBySearch() {
		if (!searchInput.trim() || searchInput.trim().length < 2) { plots = []; return; }
		loading = true;
		try { plots = await feasibility.searchLandPlots(area, searchInput.trim()); }
		catch { plots = []; }
		finally { loading = false; }
	}

	async function fetchBySize() {
		const size = parseFloat(sizeInput);
		if (!sizeInput || isNaN(size) || size <= 0) { plots = []; return; }
		loading = true;
		try { plots = await feasibility.getLandPlots(area, size); }
		catch { plots = []; }
		finally { loading = false; }
	}

	function onInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(mode === 'search' ? fetchBySearch : fetchBySize, 400);
	}

	function switchMode(m: 'search' | 'size') {
		mode = m;
		searchInput = '';
		sizeInput = '';
		plots = [];
	}
</script>

<div class="max-w-xl mx-auto">
	<h2 class="text-xl font-semibold text-slate-800 mb-1">Find your land plot</h2>
	<p class="text-sm text-slate-500 mb-5">
		Search for a plot in <span class="text-teal-600 font-medium">{area}</span>.
	</p>

	<!-- Mode toggle -->
	<div class="flex gap-1 p-1 bg-slate-100 rounded-lg mb-5 w-fit">
		<button
			type="button"
			class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {mode === 'search' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
			onclick={() => switchMode('search')}
		>By plot / project name</button>
		<button
			type="button"
			class="px-3 py-1.5 text-xs font-medium rounded-md transition-colors {mode === 'size' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'}"
			onclick={() => switchMode('size')}
		>By size</button>
	</div>

	{#if mode === 'search'}
		<div class="relative mb-6">
			<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
				<svg class="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
				</svg>
			</div>
			<input
				type="text"
				class="w-full pl-9 pr-4 py-3 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
				placeholder="Plot number or project name..."
				bind:value={searchInput}
				oninput={onInput}
			/>
		</div>
	{:else}
		<div class="mb-6">
			<input
				type="number"
				class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
				placeholder="Plot size (sqm)"
				bind:value={sizeInput}
				oninput={onInput}
				min="0"
			/>
		</div>
	{/if}

	{#if loading}
		<div class="flex items-center gap-2 text-sm text-slate-400 py-4">
			<div class="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin"></div>
			Searching land registry...
		</div>
	{:else if plots.length === 0 && (searchInput || sizeInput)}
		<p class="text-sm text-slate-400 py-4">No matching plots found.</p>
	{:else if plots.length > 0}
		<div class="space-y-3">
			{#each plots as p}
				<button
					type="button"
					class="w-full text-left p-4 rounded-xl border border-slate-200 bg-white hover:border-teal-400 hover:bg-teal-50 transition-all group"
					onclick={() => onSelect(p)}
				>
					<div class="flex items-start justify-between gap-2">
						<div>
							<p class="text-sm font-semibold text-slate-800 group-hover:text-teal-700">
								{p.land_number ?? `Plot ${p.property_id}`}
							</p>
							<p class="text-xs text-slate-500 mt-0.5">{p.property_type_en ?? 'Land'}</p>
							{#if p.project_name_en}
								<p class="text-xs text-slate-400">{p.project_name_en}</p>
							{/if}
						</div>
						<div class="text-right flex-shrink-0">
							<p class="text-sm font-bold text-slate-800">{fmt(p.actual_area)} sqm</p>
							<div class="flex flex-wrap gap-1 justify-end mt-1">
								{#if p.land_type_en}
									<span class="px-2 py-0.5 rounded-full bg-blue-100 text-blue-700 text-xs font-medium">
										{p.land_type_en}
									</span>
								{/if}
								{#if p.is_free_hold}
									<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-medium">
										Freehold
									</span>
								{/if}
							</div>
						</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
