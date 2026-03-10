<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number) {
		return isNaN(n) ? '—' : `${n.toFixed(1)}%`;
	}

	const s = $derived(feasibilityStore);
</script>

<div class="space-y-3">
	{#if s.plotDossier}
		<div class="rounded border border-slate-200 bg-slate-50 px-2.5 py-2 text-[11px] text-slate-600">
			<span class="font-semibold text-slate-800">{s.plotDossier.plot_number}</span>
			· {s.plotDossier.community_name}
			· {Math.round(s.plotDossier.plot_area_sqm).toLocaleString('en-AE')} sqm
			{#if s.plotDossier.max_gfa_sqm > 0}
				· max GFA {Math.round(s.plotDossier.max_gfa_sqm).toLocaleString('en-AE')} sqm
			{/if}
		</div>
	{/if}

	<!-- Stat strip -->
	<div class="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-[11px] text-slate-500">
		<span class="font-semibold text-slate-700">{s.totalUnits.toLocaleString('en-AE')}</span> units
		<span class="text-slate-300">·</span>
		<span class="font-semibold text-slate-700"
			>{Math.round(s.totalSellableAreaSqm).toLocaleString('en-AE')}</span
		>
		sqm
		<span class="text-slate-300">·</span>
		<span class="font-semibold text-slate-700">AED {fmtK(s.totalGDV)}k</span> GDV
	</div>

	<!-- Key metrics -->
	<div class="rounded border border-slate-200 overflow-hidden text-[11px]">
		{#each [{ label: 'Gross Development Value', value: fmtK(s.totalGDV) }, { label: 'Total Dev Cost', value: fmtK(s.totalDevCost) }, { label: 'Gross Profit', value: fmtK(s.grossProfit) }, { label: 'Return on Cost', value: fmtPct(s.returnOnCost) }, { label: 'Equity Required', value: fmtK(s.equityRequired) }, { label: 'Unlevered IRR', value: isNaN(s.unleveredIRR) ? '—' : `${(s.unleveredIRR * 100).toFixed(1)}%` }] as row (row.label)}
			<div
				class="flex items-center justify-between px-2 py-1.5 border-b border-slate-100 last:border-0 hover:bg-slate-50/60"
			>
				<span class="text-slate-500">{row.label}</span>
				<span class="tabular-nums font-semibold text-slate-900">{row.value}</span>
			</div>
		{/each}
	</div>

	<p class="text-[10px] text-slate-400 text-center">Edit unit mix in the Assumptions tab →</p>
</div>
