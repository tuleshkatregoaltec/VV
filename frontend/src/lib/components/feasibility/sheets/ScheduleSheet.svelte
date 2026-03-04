<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}

	let sCurve = $state(false);

	const s = $derived(feasibilityStore);
	const displayQ = $derived(Math.min(s.totalQ, 20));
	const quarters = $derived(Array.from({ length: displayQ }, (_, i) => i));

	function constructionDist(q: number, cq: number): number {
		if (!sCurve) return 1 / cq;
		const third = cq / 3;
		if (q < third) return 0.25 / (cq / 3);
		if (q < 2 * third) return 0.5 / (cq / 3);
		return 0.25 / (cq / 3);
	}

	const capex = $derived(
		quarters.map((q) => {
			const land = q === 0 ? s.assumptions.landCost : 0;
			const construction = q < s.cq ? s.totalHardCost * constructionDist(q, s.cq) : 0;
			const soft = q < s.cq ? s.totalSoftCost * constructionDist(q, s.cq) : 0;
			const finance = q < s.cq ? (s.debtAmount * s.assumptions.financeRatePct) / 100 / 4 : 0;
			return { q, land, construction, soft, finance };
		}),
	);

	const salesAbs = $derived(
		quarters.map((q) => {
			const inSales = q >= s.sq && q < s.sq + s.nq;
			const sold = inSales ? Math.round(s.preHandoverUnits / s.nq) : 0;
			return { q, sold };
		}),
	);

	const cumulativeSold = $derived(
		salesAbs.reduce((acc, p) => {
			const prev = acc.length > 0 ? acc[acc.length - 1] : 0;
			acc.push(prev + p.sold);
			return acc;
		}, [] as number[]),
	);
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>

	<!-- Section A: Gantt -->
	<div class="border-b border-slate-200">
		<div class="flex items-center justify-between px-2 py-1.5 bg-slate-800 border-b border-slate-600">
			<span class="text-[10px] font-bold text-white uppercase tracking-wider">Construction &amp; Sales Schedule</span>
			{#if s.totalQ > 20}
				<span class="text-[10px] text-slate-300">Showing Q1–Q20 of {s.totalQ}</span>
			{/if}
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th class="border-r border-slate-200 text-left px-2 py-1 text-slate-600 font-semibold w-32">Phase</th>
						{#each quarters as q}
							<th class="border-r border-slate-200 text-center px-1 py-1 text-slate-500 font-normal w-8 text-[10px]">Q{q + 1}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each [
						{ label: 'Land & Approvals', start: 0, end: 0 },
						{ label: 'Construction', start: 0, end: s.cq - 1 },
						{ label: 'Pre-sales', start: s.sq, end: s.sq + s.nq - 1 },
						{ label: 'Handover', start: s.cq, end: s.cq },
					] as phase}
						<tr class="border-b border-slate-100">
							<td class="border-r border-slate-200 px-2 py-1 text-slate-600">{phase.label}</td>
							{#each quarters as q}
								<td class="border-r border-slate-100 p-0.5">
									{#if q >= phase.start && q <= phase.end && phase.end < displayQ}
										<div class="bg-teal-500 rounded text-white text-[10px] text-center py-0.5 px-0.5">●</div>
									{:else if q >= phase.start && q <= phase.end}
										<div class="bg-teal-300 rounded text-white text-[10px] text-center py-0.5 px-0.5">●</div>
									{/if}
								</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>

	<!-- Section B: Quarterly Capex -->
	<div>
		<div class="flex items-center justify-between px-2 py-1.5 bg-slate-800 border-b border-slate-600">
			<span class="text-[10px] font-bold text-white uppercase tracking-wider">Quarterly Capex ('000)</span>
			<label class="flex items-center gap-1.5 text-[10px] text-slate-300 cursor-pointer">
				<input type="checkbox" bind:checked={sCurve} class="accent-teal-500" />
				S-curve
			</label>
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse text-[11px]" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold w-32 sticky left-0 bg-slate-100">Line Item</th>
						{#each quarters as q}
							<th class="border-r border-slate-200 text-right px-1.5 py-1.5 text-slate-600 font-semibold w-14">Q{q + 1}</th>
						{/each}
						<th class="text-right px-2 py-1.5 text-slate-600 font-semibold w-16">Total</th>
					</tr>
				</thead>
				<tbody>
					{#each [
						{ label: 'Land', key: 'land' as const },
						{ label: 'Construction', key: 'construction' as const },
						{ label: 'Soft Costs', key: 'soft' as const },
						{ label: 'Finance', key: 'finance' as const },
					] as row}
						<tr class="border-b border-slate-100 hover:bg-slate-50/60">
							<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">{row.label}</td>
							{#each capex as p}
								<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
									{p[row.key] > 0 ? fmtK(p[row.key]) : '—'}
								</td>
							{/each}
							<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">
								{fmtK(capex.reduce((sum, p) => sum + p[row.key], 0))}
							</td>
						</tr>
					{/each}
					<tr class="border-t-2 border-slate-300">
						<td class="border-r border-slate-200 px-2 py-1.5 font-bold text-slate-700 sticky left-0 bg-white">Total Outflows</td>
						{#each capex as p}
							{@const total = p.land + p.construction + p.soft + p.finance}
							<td class="border-r border-slate-100 px-1.5 py-1.5 text-right font-semibold tabular-nums text-slate-900">
								{total > 0 ? fmtK(total) : '—'}
							</td>
						{/each}
						<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">
							{fmtK(capex.reduce((sum, p) => sum + p.land + p.construction + p.soft + p.finance, 0))}
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Section C: Sales Absorption -->
	<div>
		<div class="px-2 py-1.5 bg-slate-800 border-b border-slate-600">
			<span class="text-[10px] font-bold text-white uppercase tracking-wider">Sales Absorption</span>
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse text-[11px]" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold w-32 sticky left-0 bg-slate-100">Metric</th>
						{#each quarters as q}
							<th class="border-r border-slate-200 text-right px-1.5 py-1.5 text-slate-600 font-semibold w-14">Q{q + 1}</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Units Sold</td>
						{#each salesAbs as p}
							<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
								{p.sold > 0 ? p.sold : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Cumulative</td>
						{#each cumulativeSold as cum}
							<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
								{cum > 0 ? cum : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">% Sold</td>
						{#each cumulativeSold as cum}
							{@const pct = s.totalUnits > 0 ? (cum / s.totalUnits) * 100 : 0}
							<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
								{cum > 0 ? `${pct.toFixed(0)}%` : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-200">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Revenue ('000)</td>
						{#each salesAbs as p}
							{@const rev = p.sold > 0 ? (p.sold / Math.max(1, s.preHandoverUnits)) * s.preHandoverGDV : 0}
							<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
								{rev > 0 ? fmtK(rev) : '—'}
							</td>
						{/each}
					</tr>
				</tbody>
			</table>
		</div>
	</div>

</div>
