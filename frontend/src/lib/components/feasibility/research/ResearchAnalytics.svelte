<script lang="ts">
	import { onMount } from 'svelte';
	import { Chart, registerables } from 'chart.js';
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';
	import { researchPanelStore } from '$lib/stores/researchPanel.svelte';

	Chart.register(...registerables);

	function fmtK(n: number): string {
		return Math.round(n).toLocaleString('en-AE');
	}

	const agentData = $derived(researchPanelStore.agentAnalytics);
	const marketPrices = $derived(researchPanelStore.comparableMarketPrices);
	const pricePerSqm = $derived(feasibilityStore.config.pricePerSqm);

	// All unit types from either source
	const unitTypes = $derived(Object.keys(pricePerSqm));

	// Chart
	let canvas: HTMLCanvasElement | undefined = $state();
	let chart: Chart | null = null;

	function buildChart(data: NonNullable<typeof agentData>) {
		if (!canvas) return;
		chart?.destroy();
		const labels = data.trend.map((r) => r.month.slice(0, 7)); // YYYY-MM
		const values = data.trend.map((r) => r.median_price_sqm);
		chart = new Chart(canvas, {
			type: 'line',
			data: {
				labels,
				datasets: [{
					data: values,
					borderColor: '#0d9488',
					backgroundColor: 'rgba(13,148,136,0.08)',
					borderWidth: 1.5,
					pointRadius: 2,
					tension: 0.3,
					fill: true,
				}],
			},
			options: {
				responsive: true,
				maintainAspectRatio: false,
				plugins: { legend: { display: false } },
				scales: {
					x: { ticks: { font: { size: 9 }, maxTicksLimit: 6 }, grid: { display: false } },
					y: { ticks: { font: { size: 9 } }, grid: { color: '#f1f5f9' } },
				},
			},
		});
	}

	$effect(() => {
		if (agentData && canvas) buildChart(agentData);
		if (!agentData && chart) { chart.destroy(); chart = null; }
	});

	onMount(() => {
		return () => chart?.destroy();
	});
</script>

<div class="flex flex-col h-full min-h-0 overflow-y-auto scrollbar-hide">
	{#if agentData}
		<!-- Agent view -->
		<div class="px-2 py-1.5 bg-teal-50 border-b border-teal-100 text-[10px] text-teal-700 font-medium flex-shrink-0">
			Analytics — {agentData.filters.project_name || agentData.filters.area || 'area'} · {agentData.filters.days}d
		</div>

		<!-- Trend chart -->
		<div class="px-2 pt-2 flex-shrink-0" style="height: 160px;">
			<canvas bind:this={canvas}></canvas>
		</div>

		<!-- By rooms breakdown -->
		{#if agentData.by_rooms.length > 0}
			<div class="rounded border border-slate-200 overflow-hidden text-[10px] mx-2 mb-2 mt-1 flex-shrink-0">
				<div class="grid grid-cols-3 bg-slate-50 border-b border-slate-200 px-2 py-1 font-medium text-slate-400">
					<span>Type</span>
					<span class="text-right">Median/sqm</span>
					<span class="text-right">Count</span>
				</div>
				{#each agentData.by_rooms as row}
					<div class="grid grid-cols-3 px-2 py-1 border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
						<span class="text-slate-600">{row.rooms_en}</span>
						<span class="text-right tabular-nums text-slate-800 font-medium">{fmtK(row.median_price_sqm)}</span>
						<span class="text-right tabular-nums text-slate-500">{row.txn_count.toLocaleString()}</span>
					</div>
				{/each}
			</div>
		{/if}

	{:else}
		<!-- Default view: your prices vs comparable market -->
		<div class="px-2 pt-2 pb-1 flex-shrink-0">
			<p class="text-[10px] font-semibold text-slate-500 mb-1.5">Price Assumptions vs Market</p>
			{#if unitTypes.length === 0}
				<p class="text-[11px] text-slate-400">No unit types configured.</p>
			{:else}
				<div class="rounded border border-slate-200 overflow-hidden text-[10px]">
					<div class="grid grid-cols-3 bg-slate-50 border-b border-slate-200 px-2 py-1 font-medium text-slate-400">
						<span>Type</span>
						<span class="text-right">Your price</span>
						<span class="text-right">Comparable</span>
					</div>
					{#each unitTypes as type}
						{@const yours = pricePerSqm[type] ?? 0}
						{@const market = marketPrices?.[type] ?? null}
						<div class="grid grid-cols-3 px-2 py-1.5 border-b border-slate-50 last:border-0 hover:bg-slate-50/60">
							<span class="text-slate-600 font-medium">{type}</span>
							<span class="text-right tabular-nums text-slate-800">{yours > 0 ? fmtK(yours) : '—'}</span>
							<span class="text-right tabular-nums {market ? (yours > market ? 'text-emerald-600' : 'text-slate-500') : 'text-slate-300'}">
								{market ? fmtK(market) : '—'}
							</span>
						</div>
					{/each}
				</div>
				<p class="text-[9px] text-slate-300 mt-1 text-right">AED/sqm · comparable from seeded data</p>
			{/if}
		</div>

		<div class="flex-1 flex items-end justify-center pb-4 px-4 text-center">
			<p class="text-[10px] text-slate-300">Ask the agent "show me price analytics for {feasibilityStore.area || 'this area'}" for trend data.</p>
		</div>
	{/if}
</div>
