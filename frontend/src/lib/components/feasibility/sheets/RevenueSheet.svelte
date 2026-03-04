<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmt(n: number) { return n.toLocaleString('en-AE', { maximumFractionDigits: 0 }); }
	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string { return `${n.toFixed(1)}%`; }

	const sectionRow = 'bg-slate-800 border-b border-slate-600';
	const sectionCell = 'px-2 py-1.5 text-[10px] font-bold text-white uppercase tracking-wider';
</script>

<div class="overflow-auto flex-1">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>

	<!-- Section A: Unit Mix & Pricing -->
	<table class="w-full border-collapse text-[11px]">
		<thead class="sticky top-0 z-10">
			<tr class="{sectionRow}">
				<td colspan="7" class="{sectionCell}">Unit Mix &amp; Pricing</td>
			</tr>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold">Type</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Count</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Avg sqm</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Total sqm</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold w-24">AED/sqm</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">GDV ('000)</th>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">% GDV</th>
			</tr>
		</thead>
		<tbody>
			{#each feasibilityStore.spreadsheetRows as row}
				{@const totalArea = row.count * row.avgSizeSqm}
				{@const gdvPct = feasibilityStore.totalGDV > 0 ? (row.totalProceeds / feasibilityStore.totalGDV) * 100 : 0}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-700 font-medium">{row.type}</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{row.count}</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{row.avgSizeSqm.toFixed(0)}</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmt(totalArea)}</td>
					<td class="border-r border-slate-200 p-0 relative">
						{#if feasibilityStore.changedFields[row.type]}
							<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>
						{/if}
						{#if feasibilityStore.undoFields[row.type]}
							<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>
						{/if}
						<input
							type="number"
							class="w-full h-full text-right px-2 py-1.5 bg-amber-50 focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal-400 tabular-nums text-blue-800"
							value={row.pricePerSqm}
							min="0"
							step="100"
							oninput={(e) => {
								const v = parseFloat((e.target as HTMLInputElement).value);
								if (!isNaN(v)) feasibilityStore.setPricePerSqm({ [row.type]: v });
							}}
						/>
					</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(row.totalProceeds)}</td>
					<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtPct(gdvPct)}</td>
				</tr>
			{/each}
			<tr class="border-t-2 border-slate-300">
				<td class="px-2 py-1.5 font-semibold text-slate-700">Total</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{feasibilityStore.totalUnits}</td>
				<td class="border-r border-slate-200"></td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{fmt(feasibilityStore.totalSellableAreaSqm)}</td>
				<td class="border-r border-slate-200"></td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">{fmtK(feasibilityStore.totalGDV)}</td>
				<td class="px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">100.0%</td>
			</tr>
		</tbody>
	</table>

	<!-- Section B: Revenue Strategy -->
	<table class="w-full border-collapse text-[11px]">
		<thead>
			<tr class="{sectionRow}">
				<td colspan="4" class="{sectionCell}">Revenue Strategy</td>
			</tr>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold"></th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Pre-handover</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Post-handover</th>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">Total</th>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Units</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{feasibilityStore.preHandoverUnits}</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{feasibilityStore.postHandoverUnits}</td>
				<td class="px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{feasibilityStore.totalUnits}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Price basis</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right text-slate-500 text-[10px]">
					Launch ({fmtPct(-feasibilityStore.assumptions.presaleDiscountPct)})
				</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right text-slate-500 text-[10px]">Market price</td>
				<td></td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">GDV ('000)</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{fmtK(feasibilityStore.preHandoverGDV)}</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{fmtK(feasibilityStore.postHandoverGDV)}</td>
				<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">{fmtK(feasibilityStore.totalBlendedGDV)}</td>
			</tr>
		</tbody>
	</table>

	<!-- Section C: Revenue Summary -->
	<table class="w-full border-collapse text-[11px]">
		<thead>
			<tr class="{sectionRow}">
				<td colspan="2" class="{sectionCell}">Revenue Summary ('000)</td>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Total GDV (market prices)</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(feasibilityStore.totalGDV)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Blended GDV (incl. presale discount)</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(feasibilityStore.totalBlendedGDV)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500">
					Less: Agent Commission ({fmtPct(feasibilityStore.assumptions.agentCommissionPct)})
				</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(-feasibilityStore.agentFees)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500">
					Less: Marketing ({fmtPct(feasibilityStore.assumptions.marketingBudgetPct)})
				</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(-feasibilityStore.marketingCost)}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-bold text-slate-700">Net Revenue</td>
				<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">{fmtK(feasibilityStore.netRevenue)}</td>
			</tr>
		</tbody>
	</table>

</div>
