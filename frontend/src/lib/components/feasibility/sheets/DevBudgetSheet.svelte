<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	// AED '000 formatter — brackets for negatives
	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string { return `${n.toFixed(1)}%`; }

	let open = $state<Record<string, boolean>>({
		land: true, hard: true, soft: true, sales: true, finance: true,
	});
	function toggle(key: string) { open[key] = !open[key]; }

	// Editable input: yellow bg + dark blue text
	const inputClass =
		'w-full text-right px-2 py-1.5 bg-amber-50 focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal-400 tabular-nums text-blue-800 text-[11px]';

	function numInput(key: keyof typeof feasibilityStore.assumptions, e: Event) {
		const v = parseFloat((e.target as HTMLInputElement).value);
		if (!isNaN(v)) feasibilityStore.setAssumptions({ [key]: v });
	}

	const s = $derived(feasibilityStore);
	const a = $derived(feasibilityStore.assumptions);
	const cf = $derived(feasibilityStore.changedFields);
	const uf = $derived(feasibilityStore.undoFields);
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>
	<table class="w-full border-collapse">
		<tbody>

		<!-- LAND ACQUISITION -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('land')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.land ? '▼' : '▶'} Land Acquisition
			</td>
		</tr>
		{#if open.land}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 w-48">Land Purchase Price</td>
				<td class="border-r border-slate-200 p-0 w-32 relative">
					{#if cf['landCost']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['landCost']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
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
					{#if cf['transferFeePct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['transferFeePct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.transferFeePct} min="0" step="0.5" oninput={(e) => numInput('transferFeePct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.transferFees)}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Land Cost</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalLandCost)}</td>
			</tr>
		{/if}

		<!-- HARD CONSTRUCTION -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('hard')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.hard ? '▼' : '▶'} Hard Construction Costs
			</td>
		</tr>
		{#if open.hard}
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">BUA Efficiency</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['buaEfficiencyPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['buaEfficiencyPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.buaEfficiencyPct} min="1" max="100" step="1" oninput={(e) => numInput('buaEfficiencyPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ BUA {s.totalBUA > 0 ? Math.round(s.totalBUA).toLocaleString() : '—'} sqm</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Build Cost/sqm (BUA)</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['buildCostPerSqm']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['buildCostPerSqm']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.buildCostPerSqm} min="0" step="50" oninput={(e) => numInput('buildCostPerSqm', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">AED/sqm</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Contingency</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['contingencyPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['contingencyPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.contingencyPct} min="0" step="1" oninput={(e) => numInput('contingencyPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.contingencyCost)}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Hard Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900">{fmtK(s.totalHardCost)}</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">
					{s.totalSellableAreaSqm > 0 ? `${Math.round(s.totalHardCost / s.totalSellableAreaSqm).toLocaleString()} /sqm` : ''}
				</td>
			</tr>
		{/if}

		<!-- SOFT COSTS -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('soft')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.soft ? '▼' : '▶'} Soft Costs ({fmtPct(a.softCostsPct)} of hard)
			</td>
		</tr>
		{#if open.soft}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Total Soft Costs</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['softCostsPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['softCostsPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.softCostsPct} min="0" step="1" oninput={(e) => numInput('softCostsPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">%</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 pl-5 text-slate-500">└ Design & Engineering</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['designFeePct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['designFeePct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.designFeePct} min="0" step="0.5" oninput={(e) => numInput('designFeePct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.designCost)}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 pl-5 text-slate-500">└ Project Management</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['projectMgmtPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['projectMgmtPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.projectMgmtPct} min="0" step="0.5" oninput={(e) => numInput('projectMgmtPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.projectMgmtCost)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 pl-5 text-slate-400">└ Other Soft Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">
					{fmtPct(Math.max(0, a.softCostsPct - a.designFeePct - a.projectMgmtPct))}
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.otherSoftCost)} (derived)</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Soft Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalSoftCost)}</td>
			</tr>
		{/if}

		<!-- SALES & MARKETING -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('sales')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.sales ? '▼' : '▶'} Sales & Marketing
			</td>
		</tr>
		{#if open.sales}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Agent Commission</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['agentCommissionPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['agentCommissionPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.agentCommissionPct} min="0" step="0.5" oninput={(e) => numInput('agentCommissionPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.agentFees)}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Marketing Budget</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['marketingBudgetPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['marketingBudgetPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.marketingBudgetPct} min="0" step="0.5" oninput={(e) => numInput('marketingBudgetPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.marketingCost)}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Sales Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalSalesCost)}</td>
			</tr>
		{/if}

		<!-- FINANCE -->
		<tr class="bg-slate-800 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('finance')}>
			<td colspan="3" class="px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]">
				{open.finance ? '▼' : '▶'} Finance
			</td>
		</tr>
		{#if open.finance}
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Loan Amount</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.debtAmount)}</td>
				<td class="px-2 py-1.5 text-slate-400">{fmtPct(a.debtToCostRatio * 100)} of pre-finance cost</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Interest Rate p.a.</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['financeRatePct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['financeRatePct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.financeRatePct} min="0" step="0.5" oninput={(e) => numInput('financeRatePct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.totalInterest)}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Arrangement Fee</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['arrangementFeePct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['arrangementFeePct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.arrangementFeePct} min="0" step="0.25" oninput={(e) => numInput('arrangementFeePct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.arrangementFee)}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Finance Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalFinanceCost)}</td>
			</tr>
		{/if}

		<!-- TOTAL -->
		<tr class="border-t-4 border-slate-600 bg-slate-900">
			<td class="px-2 py-2 font-bold text-white">TOTAL DEVELOPMENT COST</td>
			<td class="px-2 py-2 text-right font-bold text-white tabular-nums">{fmtK(s.totalDevCost)}</td>
			<td class="px-2 py-2 text-slate-300 tabular-nums">
				{s.totalSellableAreaSqm > 0 ? `${Math.round(s.totalDevCost / s.totalSellableAreaSqm).toLocaleString()} /sqm` : ''}
			</td>
		</tr>

		</tbody>
	</table>
</div>
