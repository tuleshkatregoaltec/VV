<script lang="ts">
	import { researchPanelStore } from '$lib/stores/researchPanel.svelte';

	function fmt(n: number | null | undefined) {
		if (n === null || n === undefined) return '—';
		return Math.round(n).toLocaleString('en-AE');
	}

	const pricing = $derived(researchPanelStore.pricingComparables);
	const pipeline = $derived(researchPanelStore.pipelineComparables);
	const marketPricing = $derived(researchPanelStore.hbuMarketPricing);
</script>

<div class="flex flex-col h-full min-h-0 overflow-y-auto scrollbar-hide px-3 py-3 gap-4">
	<div class="rounded border border-slate-200 overflow-hidden text-[10px]">
		<div class="px-3 py-2 bg-slate-50 border-b border-slate-200">
			<p class="font-semibold text-slate-700">Segmented market pricing</p>
		</div>
		{#if marketPricing.length === 0}
			<div class="px-3 py-3 text-slate-400">No HBU pricing evidence loaded yet.</div>
		{:else}
			<div class="grid grid-cols-4 px-3 py-1.5 border-b border-slate-100 text-slate-400 font-medium uppercase tracking-[0.1em]">
				<span>Type</span>
				<span class="text-right">Median/sqm</span>
				<span class="text-right">Avg sqm</span>
				<span class="text-right">Txns</span>
			</div>
			{#each marketPricing as row (row.unit_type)}
				<div class="grid grid-cols-4 px-3 py-2 border-b border-slate-50 last:border-0">
					<span class="text-slate-700 font-medium">{row.unit_type}</span>
					<span class="text-right text-slate-800">{fmt(row.median_price_sqm)}</span>
					<span class="text-right text-slate-500">{fmt(row.avg_area_sqm)}</span>
					<span class="text-right text-slate-500">{fmt(row.transaction_count)}</span>
				</div>
			{/each}
		{/if}
	</div>

	<div class="rounded border border-slate-200 overflow-hidden text-[10px]">
		<div class="px-3 py-2 bg-slate-50 border-b border-slate-200">
			<p class="font-semibold text-slate-700">Pricing comparables</p>
		</div>
		{#if pricing.length === 0}
			<div class="px-3 py-3 text-slate-400">No pricing comparables loaded yet.</div>
		{:else}
			{#each pricing as comp (`pricing-${comp.project_id}`)}
				<div class="px-3 py-2.5 border-b border-slate-50 last:border-0">
					<div class="flex items-start justify-between gap-2">
						<div>
							<p class="text-slate-800 font-medium">{comp.project_name}</p>
							<p class="text-slate-500">{comp.area_name}</p>
						</div>
						<div class="text-right">
							<p class="text-slate-800 font-medium">Score {comp.score}</p>
							<p class="text-slate-500">{comp.median_price_sqm ? `${fmt(comp.median_price_sqm)}/sqm` : '—'}</p>
						</div>
					</div>
					<div class="flex flex-wrap gap-2 mt-2 text-slate-500">
						<span>Land {fmt(comp.total_land_area_sqm)} sqm</span>
						<span>Delta {comp.land_area_delta_pct ?? '—'}%</span>
						<span>{comp.dominant_unit_type || 'Unknown type'}</span>
					</div>
				</div>
			{/each}
		{/if}
	</div>

	<div class="rounded border border-slate-200 overflow-hidden text-[10px]">
		<div class="px-3 py-2 bg-slate-50 border-b border-slate-200">
			<p class="font-semibold text-slate-700">Pipeline competition</p>
		</div>
		{#if pipeline.length === 0}
			<div class="px-3 py-3 text-slate-400">No pipeline comparables loaded yet.</div>
		{:else}
			{#each pipeline as comp (`pipeline-${comp.project_id}`)}
				<div class="px-3 py-2.5 border-b border-slate-50 last:border-0">
					<div class="flex items-start justify-between gap-2">
						<div>
							<p class="text-slate-800 font-medium">{comp.project_name}</p>
							<p class="text-slate-500">{comp.project_status || 'Unknown status'}</p>
						</div>
						<p class="text-slate-800 font-medium">Score {comp.score}</p>
					</div>
					<div class="flex flex-wrap gap-2 mt-2 text-slate-500">
						<span>Land {fmt(comp.total_land_area_sqm)} sqm</span>
						<span>Delta {comp.land_area_delta_pct ?? '—'}%</span>
						<span>{comp.dominant_unit_type || 'Unknown type'}</span>
					</div>
				</div>
			{/each}
		{/if}
	</div>
</div>
