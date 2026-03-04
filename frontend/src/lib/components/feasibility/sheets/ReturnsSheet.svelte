<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string { return isNaN(n) ? '—' : `${n.toFixed(1)}%`; }
	function fmtIRR(n: number): string { return isNaN(n) ? '—' : `${(n * 100).toFixed(1)}%`; }

	type Axis = 'Price/sqm' | 'Build Cost/sqm' | 'Finance Rate' | 'Sales Velocity';
	const axisOptions: Axis[] = ['Price/sqm', 'Build Cost/sqm', 'Finance Rate', 'Sales Velocity'];
	let axisX = $state<Axis>('Price/sqm');
	let axisY = $state<Axis>('Build Cost/sqm');
	const steps = [-0.1, 0, 0.1];

	const s = $derived(feasibilityStore);

	function rocAtFactors(pa: number, ca: number): string {
		if (axisX === 'Sales Velocity' || axisY === 'Sales Velocity') return 'N/A';
		const gdvAdj = s.totalGDV * (1 + pa);
		const devCostAdj = s.totalDevCost * (1 + ca);
		const profit = gdvAdj - devCostAdj;
		const roc = devCostAdj > 0 ? (profit / devCostAdj) * 100 : 0;
		return fmtPct(roc);
	}

	function rocClass(pa: number, ca: number): string {
		if (axisX === 'Sales Velocity' || axisY === 'Sales Velocity') return 'text-slate-400';
		const gdvAdj = s.totalGDV * (1 + pa);
		const devCostAdj = s.totalDevCost * (1 + ca);
		const profit = gdvAdj - devCostAdj;
		const roc = devCostAdj > 0 ? (profit / devCostAdj) * 100 : 0;
		const target = s.assumptions.targetROCPct;
		if (roc >= target) return 'bg-emerald-50 text-emerald-700 font-semibold';
		if (roc >= target * 0.75) return 'bg-amber-50 text-amber-700 font-semibold';
		return 'bg-red-50 text-red-700 font-semibold';
	}

	function axisFactors(axis: Axis, step: number): { pa: number; ca: number } {
		switch (axis) {
			case 'Price/sqm': return { pa: step, ca: 0 };
			case 'Build Cost/sqm': return { pa: 0, ca: step };
			case 'Finance Rate': {
				const adjFinance = s.totalInterest * (1 + step);
				const adjDevCost = s.preFinanceCost + adjFinance + s.arrangementFee;
				const ca = s.totalDevCost > 0 ? (adjDevCost - s.totalDevCost) / s.totalDevCost : 0;
				return { pa: 0, ca };
			}
			case 'Sales Velocity': return { pa: 0, ca: 0 };
		}
	}

	function cellFactors(rowStep: number, colStep: number): { pa: number; ca: number } {
		const row = axisFactors(axisY, rowStep);
		const col = axisFactors(axisX, colStep);
		return { pa: row.pa + col.pa, ca: row.ca + col.ca };
	}

	function stepLabel(axis: Axis, step: number) {
		if (step === 0) return 'Base';
		const sign = step > 0 ? '+' : '';
		return `${sign}${(step * 100).toFixed(0)}%`;
	}

	const leveredProfit = $derived(s.netRevenue - s.debtAmount - s.totalInterest);

	const sectionRow = 'bg-slate-800 border-b border-slate-600';
	const sectionCell = 'px-2 py-1.5 text-[10px] font-bold text-white uppercase tracking-wider';
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>

	<!-- Section A: Returns Table -->
	<table class="w-full border-collapse">
		<thead>
			<tr class="{sectionRow}">
				<td colspan="3" class="{sectionCell}">Returns Summary</td>
			</tr>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold">Metric</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Unlevered</th>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">Levered</th>
			</tr>
		</thead>
		<tbody>
			<!-- Green: these totals are imported from DevBudget and Revenue tabs -->
			<tr class="border-b border-slate-100 bg-green-50">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Total Investment</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.totalDevCost)}</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.equityRequired)}</td>
			</tr>
			<tr class="border-b border-slate-100 bg-green-50">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Gross Revenue</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.totalGDV)}</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.netRevenue)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Gross Profit</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{fmtK(s.grossProfit)}</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{fmtK(leveredProfit)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Profit Margin</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtPct(s.totalGDV > 0 ? (s.grossProfit / s.totalGDV) * 100 : 0)}</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtPct(s.netRevenue > 0 ? (leveredProfit / s.netRevenue) * 100 : 0)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Return on Cost</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{fmtPct(s.returnOnCost)}</td>
				<td class="px-2 py-1.5 text-slate-300">—</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Return on Equity</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-300">—</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{fmtPct(s.returnOnEquity)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Equity Multiple</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-300">—</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{isNaN(s.equityMultiple) ? '—' : `${s.equityMultiple.toFixed(2)}x`}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">IRR (annualised)</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900">{fmtIRR(s.unleveredIRR)}</td>
				<td class="px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900">{fmtIRR(s.leveredIRR)}</td>
			</tr>
		</tbody>
	</table>

	<!-- Section B: Sensitivity (ROC) — heatmap colors retained -->
	<table class="w-full border-collapse">
		<thead>
			<tr class="{sectionRow}">
				<td colspan="5" class="{sectionCell}">ROC Sensitivity</td>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 w-24">Rows (Y)</td>
				<td colspan="4" class="px-2 py-1.5">
					<select bind:value={axisY} class="text-[11px] border border-slate-300 rounded px-1.5 py-0.5 bg-white text-slate-700">
						{#each axisOptions.filter(o => o !== axisX) as opt}
							<option value={opt}>{opt}</option>
						{/each}
					</select>
				</td>
			</tr>
			<tr class="border-b border-slate-200">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Cols (X)</td>
				<td colspan="4" class="px-2 py-1.5">
					<select bind:value={axisX} class="text-[11px] border border-slate-300 rounded px-1.5 py-0.5 bg-white text-slate-700">
						{#each axisOptions.filter(o => o !== axisY) as opt}
							<option value={opt}>{opt}</option>
						{/each}
					</select>
				</td>
			</tr>
		</tbody>
	</table>
	<table class="w-full border-collapse">
		<thead>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 px-2 py-1.5 text-slate-500 font-normal text-left w-24">↓Y \ X→</th>
				{#each steps as cs}
					<th class="border-r border-slate-200 px-2 py-1.5 text-slate-600 font-semibold text-center">{stepLabel(axisX, cs)}</th>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each steps as rs}
				<tr class="border-b border-slate-100">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 font-semibold">{stepLabel(axisY, rs)}</td>
					{#each steps as cs}
						{@const { pa, ca } = cellFactors(rs, cs)}
						<td class="border-r border-slate-100 px-2 py-1.5 text-center tabular-nums {rocClass(pa, ca)}">
							{rocAtFactors(pa, ca)}
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
	<div class="flex gap-4 px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-200">
		<span class="flex items-center gap-1"><span class="inline-block w-3 h-3 rounded bg-emerald-50 border border-emerald-200"></span> ≥ target ({s.assumptions.targetROCPct}%)</span>
		<span class="flex items-center gap-1"><span class="inline-block w-3 h-3 rounded bg-amber-50 border border-amber-200"></span> ≥ 75% of target</span>
		<span class="flex items-center gap-1"><span class="inline-block w-3 h-3 rounded bg-red-50 border border-red-200"></span> below 75% of target</span>
	</div>

	<!-- Section C: Yield Analysis -->
	<table class="w-full border-collapse">
		<thead>
			<tr class="{sectionRow}">
				<td colspan="6" class="{sectionCell}">Yield Analysis</td>
			</tr>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold">Type</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Price/sqm</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold w-24">Rent/sqm/yr</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Gross Yield</th>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold">Net Yield</th>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">Implied Value ('000)</th>
			</tr>
		</thead>
		<tbody>
			{#each feasibilityStore.spreadsheetRows as row}
				{@const price = row.pricePerSqm}
				{@const defaultRent = price * s.assumptions.rentalYieldPct / 100}
				{@const rent = s.rentalRatesPerSqm[row.type] ?? defaultRent}
				{@const grossYield = price > 0 ? (rent / price) * 100 : 0}
				{@const netYield = grossYield * 0.85}
				{@const impliedVal = s.assumptions.rentalYieldPct > 0 ? (rent / (s.assumptions.rentalYieldPct / 100)) : 0}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-700 font-medium">{row.type}</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{price.toLocaleString()}</td>
					<td class="border-r border-slate-200 p-0">
						<input
							type="number"
							class="w-full text-right px-2 py-1.5 bg-amber-50 focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal-400 tabular-nums text-blue-800"
							value={Math.round(rent)}
							min="0"
							step="100"
							oninput={(e) => {
								const v = parseFloat((e.target as HTMLInputElement).value);
								if (!isNaN(v)) feasibilityStore.setRentalRate(row.type, v);
							}}
						/>
					</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtPct(grossYield)}</td>
					<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtPct(netYield)}</td>
					<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(impliedVal)}</td>
				</tr>
			{/each}
		</tbody>
	</table>

</div>
