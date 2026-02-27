<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	let landCost = $state(0);

	const netProceeds = $derived(feasibilityStore.totalGDV - landCost);

	function fmt(n: number) {
		return n.toLocaleString('en-AE', { maximumFractionDigits: 0 });
	}

	function fmtM(n: number) {
		if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
		if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
		return fmt(n);
	}

	function exportCsv() {
		const rows = feasibilityStore.spreadsheetRows;
		const lines = [
			['Unit Type', 'Count', 'Avg Size (sqm)', 'Price/sqm (AED)', 'Total Proceeds (AED)'].join(','),
			...rows.map((r) => [r.type, r.count, r.avgSizeSqm.toFixed(1), r.pricePerSqm, r.totalProceeds].join(',')),
			'',
			`Total Units,${feasibilityStore.totalUnits}`,
			`Total Sellable Area (sqm),${feasibilityStore.totalSellableAreaSqm.toFixed(0)}`,
			`Total GDV (AED),${feasibilityStore.totalGDV}`,
			`Land Cost (AED),${landCost}`,
			`Net Proceeds (AED),${netProceeds}`,
		];
		const blob = new Blob([lines.join('\n')], { type: 'text/csv' });
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		a.download = 'feasibility-study.csv';
		a.click();
		URL.revokeObjectURL(url);
	}
</script>

<div class="h-full flex flex-col overflow-hidden bg-white border-r border-slate-200">
	<!-- Header -->
	<div class="flex items-center justify-between px-4 py-3 border-b border-slate-200 flex-shrink-0">
		<h2 class="text-sm font-semibold text-slate-800">Feasibility Summary</h2>
		<button
			type="button"
			class="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-teal-600 text-white text-xs font-medium hover:bg-teal-700 transition-colors"
			onclick={exportCsv}
			title="Export to CSV"
		>
			<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
			</svg>
			Export CSV
		</button>
	</div>

	<div class="flex-1 overflow-y-auto px-4 py-4 space-y-6 text-xs">
		<!-- Unit revenue -->
		<section>
			<h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Unit Revenue</h3>
			<table class="w-full">
				<thead>
					<tr class="text-slate-400 border-b border-slate-100">
						<th class="text-left pb-1.5 font-medium">Type</th>
						<th class="text-right pb-1.5 font-medium">Qty</th>
						<th class="text-right pb-1.5 font-medium">Avg sqm</th>
						<th class="text-right pb-1.5 font-medium">AED/sqm</th>
					</tr>
				</thead>
				<tbody>
					{#each feasibilityStore.spreadsheetRows as row}
						<tr class="border-b border-slate-50 hover:bg-slate-50 transition-colors">
							<td class="py-1.5 font-medium text-slate-700">{row.type}</td>
							<td class="py-1.5 text-right text-slate-600">{row.count}</td>
							<td class="py-1.5 text-right text-slate-600">{row.avgSizeSqm.toFixed(0)}</td>
							<td class="py-1.5 text-right">
								<input
									type="number"
									class="w-20 text-right bg-transparent border-b border-transparent hover:border-slate-200 focus:border-teal-400 focus:outline-none text-slate-800"
									value={row.pricePerSqm}
									min="0"
									step="100"
									oninput={(e) => {
										const v = parseFloat((e.target as HTMLInputElement).value);
										if (!isNaN(v)) feasibilityStore.setPricePerSqm({ [row.type]: v });
									}}
								/>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</section>

		<!-- Proceeds by type -->
		<section>
			<h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Proceeds by Type</h3>
			{#each feasibilityStore.spreadsheetRows as row}
				<div class="flex justify-between py-1 border-b border-slate-50">
					<span class="text-slate-600">{row.type}</span>
					<span class="font-medium text-slate-800">AED {fmtM(row.totalProceeds)}</span>
				</div>
			{/each}
		</section>

		<!-- Totals -->
		<section>
			<h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Project Totals</h3>
			<div class="space-y-1">
				<div class="flex justify-between py-1">
					<span class="text-slate-600">Total Units</span>
					<span class="font-medium text-slate-800">{fmt(feasibilityStore.totalUnits)}</span>
				</div>
				<div class="flex justify-between py-1">
					<span class="text-slate-600">Sellable Area</span>
					<span class="font-medium text-slate-800">{fmt(feasibilityStore.totalSellableAreaSqm)} sqm</span>
				</div>
				<div class="flex justify-between py-1 border-t border-slate-100 pt-2 mt-1">
					<span class="font-semibold text-slate-700">Total GDV</span>
					<span class="font-bold text-teal-700">AED {fmtM(feasibilityStore.totalGDV)}</span>
				</div>
			</div>
		</section>

		<!-- Land cost -->
		<section>
			<h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Land Cost</h3>
			<div class="flex items-center gap-2">
				<span class="text-slate-500 flex-shrink-0">AED</span>
				<input
					type="number"
					class="flex-1 px-2 py-1.5 rounded-lg border border-slate-200 text-slate-800 focus:outline-none focus:ring-1 focus:ring-teal-400"
					bind:value={landCost}
					min="0"
					step="100000"
					placeholder="0"
				/>
			</div>
		</section>

		<!-- Net proceeds -->
		<section class="rounded-xl p-3 {netProceeds >= 0 ? 'bg-emerald-50 border border-emerald-100' : 'bg-red-50 border border-red-100'}">
			<div class="flex justify-between items-center">
				<span class="font-semibold {netProceeds >= 0 ? 'text-emerald-700' : 'text-red-700'}">Net Proceeds</span>
				<span class="font-bold text-sm {netProceeds >= 0 ? 'text-emerald-700' : 'text-red-600'}">
					AED {fmtM(netProceeds)}
				</span>
			</div>
			{#if feasibilityStore.totalGDV > 0}
				<p class="text-xs mt-1 {netProceeds >= 0 ? 'text-emerald-600' : 'text-red-500'}">
					{((netProceeds / feasibilityStore.totalGDV) * 100).toFixed(1)}% margin
				</p>
			{/if}
		</section>
	</div>
</div>
