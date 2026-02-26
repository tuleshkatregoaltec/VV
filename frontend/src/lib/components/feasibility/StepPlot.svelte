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

	let sizeInput = $state('');
	let plots = $state<LandPlot[]>([]);
	let loading = $state(false);
	let debounceTimer: ReturnType<typeof setTimeout>;

	function fmt(n: number) {
		return n.toLocaleString('en-AE', { maximumFractionDigits: 0 });
	}

	async function fetchPlots() {
		const size = parseFloat(sizeInput);
		if (!sizeInput || isNaN(size) || size <= 0) {
			plots = [];
			return;
		}
		loading = true;
		try {
			plots = await feasibility.getLandPlots(area, size);
		} catch {
			plots = [];
		} finally {
			loading = false;
		}
	}

	function onInput() {
		clearTimeout(debounceTimer);
		debounceTimer = setTimeout(fetchPlots, 500);
	}
</script>

<div class="max-w-xl mx-auto">
	<h2 class="text-xl font-semibold text-slate-800 mb-1">Find your land plot</h2>
	<p class="text-sm text-slate-500 mb-6">
		Enter approximate plot size to find matching registered land in <span class="text-teal-600 font-medium">{area}</span>.
	</p>

	<div class="flex gap-3 mb-6">
		<div class="relative flex-1">
			<input
				type="number"
				class="w-full px-4 py-3 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
				placeholder="Plot size (sqm)"
				bind:value={sizeInput}
				oninput={onInput}
				min="0"
			/>
		</div>
	</div>

	{#if loading}
		<div class="flex items-center gap-2 text-sm text-slate-400 py-4">
			<div class="w-4 h-4 border-2 border-teal-400 border-t-transparent rounded-full animate-spin"></div>
			Searching land registry...
		</div>
	{:else if plots.length === 0 && sizeInput}
		<p class="text-sm text-slate-400 py-4">No matching plots found. Try a different size.</p>
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
							{#if p.is_free_hold}
								<span class="inline-block mt-1 px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 text-xs font-medium">
									Freehold
								</span>
							{/if}
						</div>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>
