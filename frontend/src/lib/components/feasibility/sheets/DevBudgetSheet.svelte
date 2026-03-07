<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string { return `${n.toFixed(1)}%`; }

	let open = $state<Record<string, boolean>>({
		land: true, hard: true, infra: true, prof: true, sales: true, finance: true,
		inflation: false, vat: false,
	});
	function toggle(key: string) { open[key] = !open[key]; }

	const inputClass =
		'w-full text-right px-2 py-1.5 bg-amber-50 focus:outline focus:outline-2 focus:-outline-offset-2 focus:outline-teal-400 tabular-nums text-blue-800 text-[11px]';

	function numInput(key: keyof typeof feasibilityStore.assumptions, e: Event) {
		const v = parseFloat((e.target as HTMLInputElement).value);
		if (!isNaN(v)) feasibilityStore.setAssumptions({ [key]: v });
	}
	function kInput(key: keyof typeof feasibilityStore.assumptions, e: Event) {
		const v = parseFloat((e.target as HTMLInputElement).value);
		if (!isNaN(v)) feasibilityStore.setAssumptions({ [key]: v * 1000 });
	}

	const s = $derived(feasibilityStore);
	const a = $derived(feasibilityStore.assumptions);
	const cf = $derived(feasibilityStore.changedFields);
	const uf = $derived(feasibilityStore.undoFields);

	function pctOfHard(abs: number): string {
		return s.totalHardCost > 0 ? `≈ ${((abs / s.totalHardCost) * 100).toFixed(1)}% of hard` : "AED '000";
	}

	const sectionRow = 'bg-slate-800 cursor-pointer select-none border-b border-slate-600';
	const sectionCell = 'px-2 py-1.5 font-bold text-white uppercase tracking-wider text-[10px]';
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>
	<table class="w-full border-collapse">
		<tbody>

		<!-- LAND ACQUISITION -->
		<tr class={sectionRow} onclick={() => toggle('land')}>
			<td colspan="3" class={sectionCell}>{open.land ? '▼' : '▶'} Land Acquisition</td>
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

		<!-- HARD CONSTRUCTION COSTS -->
		<tr class={sectionRow} onclick={() => toggle('hard')}>
			<td colspan="3" class={sectionCell}>{open.hard ? '▼' : '▶'} Hard Construction Costs</td>
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

		<!-- INFRASTRUCTURE & AUTHORITY FEES -->
		<tr class={sectionRow} onclick={() => toggle('infra')}>
			<td colspan="3" class={sectionCell}>
				{open.infra ? '▼' : '▶'} Infrastructure & Authority Fees
				<span class="text-yellow-300 text-[9px] normal-case ml-2">soft costs are line-item driven only</span>
			</td>
		</tr>
		{#if open.infra}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Infrastructure Costs</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['infrastructureCostAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['infrastructureCostAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.infrastructureCostAED / 1000)} min="0" step="100"
						oninput={(e) => kInput('infrastructureCostAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.infrastructureCostAED > 0 ? pctOfHard(a.infrastructureCostAED) : "AED '000"}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Authority / NOC / Connection Fees</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['authorityConnectionFeesAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['authorityConnectionFeesAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.authorityConnectionFeesAED / 1000)} min="0" step="50"
						oninput={(e) => kInput('authorityConnectionFeesAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.authorityConnectionFeesAED > 0 ? pctOfHard(a.authorityConnectionFeesAED) : "AED '000"}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Community / Master Dev Fees</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['communityMasterDevFeesAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['communityMasterDevFeesAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.communityMasterDevFeesAED / 1000)} min="0" step="50"
						oninput={(e) => kInput('communityMasterDevFeesAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.communityMasterDevFeesAED > 0 ? pctOfHard(a.communityMasterDevFeesAED) : "AED '000"}</td>
			</tr>
			{#if a.hasDemolition}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Demolition</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['demolitionCostAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['demolitionCostAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.demolitionCostAED / 1000)} min="0" step="50"
						oninput={(e) => kInput('demolitionCostAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">AED '000</td>
			</tr>
			{/if}
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Infrastructure</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalInfrastructureCost)}</td>
			</tr>
		{/if}

		<!-- PROFESSIONAL FEES -->
		<tr class={sectionRow} onclick={() => toggle('prof')}>
			<td colspan="3" class={sectionCell}>{open.prof ? '▼' : '▶'} Professional Fees</td>
		</tr>
		{#if open.prof}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Design & Supervision</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['designSupervisionAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['designSupervisionAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.designSupervisionAED / 1000)} min="0" step="100"
						oninput={(e) => kInput('designSupervisionAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.designSupervisionAED > 0 ? pctOfHard(a.designSupervisionAED) : "AED '000"}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Project Management</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['projectMgmtAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['projectMgmtAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.projectMgmtAED / 1000)} min="0" step="100"
						oninput={(e) => kInput('projectMgmtAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.projectMgmtAED > 0 ? pctOfHard(a.projectMgmtAED) : "AED '000"}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Other Professional Fees</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['otherProfessionalFeesAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['otherProfessionalFeesAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.otherProfessionalFeesAED / 1000)} min="0" step="50"
						oninput={(e) => kInput('otherProfessionalFeesAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400 tabular-nums">{a.otherProfessionalFeesAED > 0 ? pctOfHard(a.otherProfessionalFeesAED) : "AED '000"}</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Professional Fees</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalProfessionalFees)}</td>
			</tr>
		{/if}

		<!-- TOTAL SOFT COSTS (sub-total line) -->
		{#if s.absoluteSoftCostTotal > 0}
		<tr class="border-b border-slate-200 bg-slate-50">
			<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500 pl-4 italic text-[10px]">Total Soft Costs (Infra + Professional)</td>
			<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-700 font-medium" colspan="2">{fmtK(s.totalSoftCost)}</td>
		</tr>
		{/if}

		<!-- SALES & MARKETING -->
		<tr class={sectionRow} onclick={() => toggle('sales')}>
			<td colspan="3" class={sectionCell}>{open.sales ? '▼' : '▶'} Sales & Marketing</td>
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
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Marketing Launch Budget</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['marketingLaunchAED']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['marketingLaunchAED']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={Math.round(a.marketingLaunchAED / 1000)} min="0" step="50"
						oninput={(e) => kInput('marketingLaunchAED', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-400">AED '000</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700">Total Sales Costs</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right font-semibold tabular-nums text-slate-900" colspan="2">{fmtK(s.totalSalesCost)}</td>
			</tr>
		{/if}

		<!-- FINANCE -->
		<tr class={sectionRow} onclick={() => toggle('finance')}>
			<td colspan="3" class={sectionCell}>{open.finance ? '▼' : '▶'} Finance</td>
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
			{#if a.hasVATBridgeLoan}
			<tr class="border-b border-amber-100 bg-amber-50/40">
				<td class="border-r border-slate-200 px-2 py-1.5 pl-4 text-amber-800">
					VAT Bridge Loan Interest
					<span class="ml-1.5 text-[9px] text-amber-600">{a.vatBridgeLoanTermMonths}m @ {a.vatBridgeLoanRatePct}%</span>
				</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-amber-900 font-medium" colspan="2">{fmtK(s.vatBridgeLoanInterest)}</td>
			</tr>
			{/if}
		{/if}

		<!-- COST INFLATION (collapsed by default) -->
		<tr class="bg-slate-700 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('inflation')}>
			<td colspan="3" class={sectionCell}>
				{open.inflation ? '▼' : '▶'} Cost Inflation
				{#if a.midPointInflationPct > 0}<span class="text-yellow-300 text-[9px] normal-case ml-2">+{fmtK(s.inflationOnCosts)}</span>{/if}
			</td>
		</tr>
		{#if open.inflation}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Mid-point Inflation</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['midPointInflationPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['midPointInflationPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.midPointInflationPct} min="0" step="0.5" oninput={(e) => numInput('midPointInflationPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.inflationOnCosts)}</td>
			</tr>
		{/if}

		<!-- VAT MEMO (collapsed by default) -->
		<tr class="bg-slate-700 cursor-pointer select-none border-b border-slate-600" onclick={() => toggle('vat')}>
			<td colspan="3" class={sectionCell}>
				{open.vat ? '▼' : '▶'} VAT
				<span class="text-slate-400 text-[9px] normal-case ml-2">memo — typically fully recoverable</span>
			</td>
		</tr>
		{#if open.vat}
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">VAT Rate on Costs</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['vatRateOnCostsPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['vatRateOnCostsPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.vatRateOnCostsPct} min="0" step="1" oninput={(e) => numInput('vatRateOnCostsPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.vatOnCosts)}</td>
			</tr>
			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Input VAT Recovery</td>
				<td class="border-r border-slate-200 p-0 relative">
					{#if cf['vatRecoveryPct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
					{#if uf['vatRecoveryPct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
					<input type="number" class={inputClass} value={a.vatRecoveryPct} min="0" max="100" step="10" oninput={(e) => numInput('vatRecoveryPct', e)} />
				</td>
				<td class="px-2 py-1.5 text-slate-500 tabular-nums">→ {fmtK(s.vatRecovery)} recovered</td>
			</tr>
			<tr class="border-t border-slate-200">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500 italic">Net VAT Position</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-700 font-medium" colspan="2">{fmtK(s.netVATPosition)}</td>
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

		<!-- CORPORATE TAX + NET PROFIT -->
		<tr class="border-b border-slate-200 bg-slate-800/20">
			<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500 italic">
				Corporate Tax ({fmtPct(a.corporateTaxRatePct)} on gross profit)
			</td>
			<td class="border-r border-slate-200 p-0 relative">
				{#if cf['corporateTaxRatePct']}<div class="absolute inset-0 field-flash pointer-events-none rounded-sm"></div>{/if}
				{#if uf['corporateTaxRatePct']}<div class="absolute inset-0 field-flash-undo pointer-events-none rounded-sm"></div>{/if}
				<input type="number" class="{inputClass} bg-slate-100/60 text-slate-500" value={a.corporateTaxRatePct} min="0" step="1"
					oninput={(e) => numInput('corporateTaxRatePct', e)} />
			</td>
			<td class="px-2 py-1.5 text-slate-500 tabular-nums">({fmtK(s.corporateTaxProvision)})</td>
		</tr>
		<tr class="border-b border-slate-300 bg-slate-50">
			<td class="border-r border-slate-200 px-2 py-2 font-bold text-slate-700">NET PROFIT (post-tax)</td>
			<td class="border-r border-slate-200 px-2 py-2 text-right font-bold tabular-nums {s.netProfit >= 0 ? 'text-emerald-700' : 'text-red-600'}" colspan="2">
				{fmtK(s.netProfit)}
			</td>
		</tr>

		</tbody>
	</table>
</div>
