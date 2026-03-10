<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}

	const s = $derived(feasibilityStore);
	const displayQ = $derived(Math.min(s.totalQ, 20));
	const quarters = $derived(Array.from({ length: displayQ }, (_, i) => i));

	const capex = $derived(
		quarters.map((q) => {
			const w = q < s.cq ? (s.capexWeights[q] ?? 0) : 0;
			const land = q === 0 ? s.assumptions.landCost : 0;
			const construction = s.totalHardCost * w;
			const soft = s.totalSoftCost * w;
			const finance = q < s.cq ? (s.debtAmount * s.assumptions.financeRatePct) / 100 / 4 : 0;
			return { q, land, construction, soft, finance };
		})
	);

	const salesAbs = $derived(
		quarters.map((q) => {
			const inSales = q >= s.sq && q < s.sq + s.nq;
			const sold = inSales ? Math.round(s.preHandoverUnits / s.nq) : 0;
			return { q, sold };
		})
	);

	const cumulativeSold = $derived(
		salesAbs.reduce((acc, p) => {
			const prev = acc.length > 0 ? acc[acc.length - 1] : 0;
			acc.push(prev + p.sold);
			return acc;
		}, [] as number[])
	);

	// Peak funding chart: cumulative outflows vs cumulative inflows
	const chartData = $derived(
		(() => {
			let cumOut = 0,
				cumIn = 0;
			return quarters.map((q) => {
				const p = capex[q];
				cumOut += p.land + p.construction + p.soft + p.finance;
				cumIn += s.cashflow[q]?.revenue ?? 0;
				return { cumOut, cumIn };
			});
		})()
	);

	const chartMax = $derived(Math.max(1, ...chartData.map((d) => Math.max(d.cumOut, d.cumIn))));
	const chartMin = $derived(Math.min(0, ...chartData.map((d) => Math.min(d.cumOut, d.cumIn))));
	const chartRange = $derived(chartMax - chartMin || 1);

	function chartY(val: number, h: number, pad: number): number {
		return pad + (1 - (val - chartMin) / chartRange) * (h - 2 * pad);
	}
	function chartX(q: number, w: number, pad: number): number {
		const n = Math.max(1, displayQ - 1);
		return pad + (q / n) * (w - 2 * pad);
	}
	function toPath(pts: Array<[number, number]>): string {
		return pts
			.map((p, i) => `${i === 0 ? 'M' : 'L'}${p[0].toFixed(1)},${p[1].toFixed(1)}`)
			.join(' ');
	}
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">
		AED '000 unless stated
	</div>

	<!-- Section A: Gantt -->
	<div class="border-b border-slate-200">
		<div
			class="flex items-center justify-between px-2 py-1.5 bg-slate-800 border-b border-slate-600"
		>
			<span class="text-[10px] font-bold text-white uppercase tracking-wider"
				>Construction &amp; Sales Schedule</span
			>
			{#if s.totalQ > 20}
				<span class="text-[10px] text-slate-300">Showing Q1–Q20 of {s.totalQ}</span>
			{/if}
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th
							class="border-r border-slate-200 text-left px-2 py-1 text-slate-600 font-semibold w-32"
							>Phase</th
						>
						{#each quarters as q}
							<th
								class="border-r border-slate-200 text-center px-1 py-1 text-slate-500 font-normal w-8 text-[10px]"
								>Q{q + 1}</th
							>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each [{ label: 'Land & Approvals', start: 0, end: 0 }, { label: 'Construction', start: 0, end: s.cq - 1 }, { label: 'Pre-sales', start: s.sq, end: s.sq + s.nq - 1 }, { label: 'Handover', start: s.cq, end: s.cq }] as phase}
						<tr class="border-b border-slate-100">
							<td class="border-r border-slate-200 px-2 py-1 text-slate-600">{phase.label}</td>
							{#each quarters as q}
								<td class="border-r border-slate-100 p-0.5">
									{#if q >= phase.start && q <= phase.end && phase.end < displayQ}
										<div
											class="bg-teal-500 rounded text-white text-[10px] text-center py-0.5 px-0.5"
										>
											●
										</div>
									{:else if q >= phase.start && q <= phase.end}
										<div
											class="bg-teal-300 rounded text-white text-[10px] text-center py-0.5 px-0.5"
										>
											●
										</div>
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
		<div
			class="flex items-center justify-between px-2 py-1.5 bg-slate-800 border-b border-slate-600"
		>
			<span class="text-[10px] font-bold text-white uppercase tracking-wider"
				>Quarterly Capex ('000)</span
			>
			<div class="flex items-center gap-1.5 text-[10px] text-slate-300">
				<span>Capex curve:</span>
				<select
					class="bg-slate-700 text-slate-200 border border-slate-600 rounded px-1 py-0.5 text-[10px] focus:outline-none"
					value={s.assumptions.capexDistributionCurve}
					onchange={(e) =>
						feasibilityStore.setAssumptions({
							capexDistributionCurve: (e.target as HTMLSelectElement).value as
								| 'linear'
								| 'sCurve'
								| 'frontLoaded'
								| 'backLoaded'
						})}
				>
					<option value="linear">Linear</option>
					<option value="sCurve">S-Curve</option>
					<option value="frontLoaded">Front-loaded</option>
					<option value="backLoaded">Back-loaded</option>
				</select>
			</div>
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse text-[11px]" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th
							class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold w-32 sticky left-0 bg-slate-100"
							>Line Item</th
						>
						{#each quarters as q}
							<th
								class="border-r border-slate-200 text-right px-1.5 py-1.5 text-slate-600 font-semibold w-14"
								>Q{q + 1}</th
							>
						{/each}
						<th class="text-right px-2 py-1.5 text-slate-600 font-semibold w-16">Total</th>
					</tr>
				</thead>
				<tbody>
					{#each [{ label: 'Land', key: 'land' as const }, { label: 'Construction', key: 'construction' as const }, { label: 'Soft Costs', key: 'soft' as const }, { label: 'Finance', key: 'finance' as const }] as row}
						<tr class="border-b border-slate-100 hover:bg-slate-50/60">
							<td
								class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white"
								>{row.label}</td
							>
							{#each capex as p}
								<td
									class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900"
								>
									{p[row.key] > 0 ? fmtK(p[row.key]) : '—'}
								</td>
							{/each}
							<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">
								{fmtK(capex.reduce((sum, p) => sum + p[row.key], 0))}
							</td>
						</tr>
					{/each}
					<tr class="border-t-2 border-slate-300">
						<td
							class="border-r border-slate-200 px-2 py-1.5 font-bold text-slate-700 sticky left-0 bg-white"
							>Total Outflows</td
						>
						{#each capex as p}
							{@const total = p.land + p.construction + p.soft + p.finance}
							<td
								class="border-r border-slate-100 px-1.5 py-1.5 text-right font-semibold tabular-nums text-slate-900"
							>
								{total > 0 ? fmtK(total) : '—'}
							</td>
						{/each}
						<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">
							{fmtK(
								capex.reduce((sum, p) => sum + p.land + p.construction + p.soft + p.finance, 0)
							)}
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Section C: Peak Funding Chart -->
	{#if displayQ > 1}
		{@const W = 480}
		{@const H = 90}
		{@const pad = 6}
		{@const data = chartData}
		<div class="border-t border-slate-200">
			<div class="px-2 py-1.5 bg-slate-800 border-b border-slate-600">
				<span class="text-[10px] font-bold text-white uppercase tracking-wider"
					>Peak Funding Profile</span
				>
			</div>
			<div class="px-3 py-3">
				<svg viewBox="0 0 {W} {H}" class="w-full" style="max-height: 90px;">
					<!-- Zero line -->
					<line
						x1={pad}
						y1={chartY(0, H, pad)}
						x2={W - pad}
						y2={chartY(0, H, pad)}
						stroke="#cbd5e1"
						stroke-width="1"
						stroke-dasharray="3,2"
					/>
					<!-- Cumulative outflows (costs) -->
					<path
						d={toPath(data.map((d, i) => [chartX(i, W, pad), chartY(d.cumOut, H, pad)]))}
						fill="none"
						stroke="#f87171"
						stroke-width="1.5"
					/>
					<!-- Cumulative inflows (revenue) -->
					<path
						d={toPath(data.map((d, i) => [chartX(i, W, pad), chartY(d.cumIn, H, pad)]))}
						fill="none"
						stroke="#14b8a6"
						stroke-width="1.5"
					/>
				</svg>
				<div class="flex gap-4 mt-1 text-[10px] text-slate-500">
					<span class="flex items-center gap-1"
						><span class="inline-block w-3 h-0.5 bg-red-400"></span>Cumul. Outflows</span
					>
					<span class="flex items-center gap-1"
						><span class="inline-block w-3 h-0.5 bg-teal-500"></span>Cumul. Inflows</span
					>
					<span class="ml-auto"
						>Peak funding: <strong class="text-slate-700"
							>{Math.round(s.peakFunding / 1000).toLocaleString('en-AE')} '000</strong
						></span
					>
				</div>
			</div>
		</div>
	{/if}

	<!-- Section D: Sales Absorption -->
	<div>
		<div class="px-2 py-1.5 bg-slate-800 border-b border-slate-600">
			<span class="text-[10px] font-bold text-white uppercase tracking-wider">Sales Absorption</span
			>
		</div>
		<div class="overflow-x-auto">
			<table class="border-collapse text-[11px]" style="min-width: max-content;">
				<thead>
					<tr class="bg-slate-100 border-b border-slate-200">
						<th
							class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold w-32 sticky left-0 bg-slate-100"
							>Metric</th
						>
						{#each quarters as q}
							<th
								class="border-r border-slate-200 text-right px-1.5 py-1.5 text-slate-600 font-semibold w-14"
								>Q{q + 1}</th
							>
						{/each}
					</tr>
				</thead>
				<tbody>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white"
							>Units Sold</td
						>
						{#each salesAbs as p}
							<td
								class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900"
							>
								{p.sold > 0 ? p.sold : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white"
							>Cumulative</td
						>
						{#each cumulativeSold as cum}
							<td
								class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900"
							>
								{cum > 0 ? cum : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-100">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white"
							>% Sold</td
						>
						{#each cumulativeSold as cum}
							{@const pct = s.totalUnits > 0 ? (cum / s.totalUnits) * 100 : 0}
							<td
								class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900"
							>
								{cum > 0 ? `${pct.toFixed(0)}%` : '—'}
							</td>
						{/each}
					</tr>
					<tr class="border-b border-slate-200">
						<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white"
							>Revenue ('000)</td
						>
						{#each salesAbs as p}
							{@const rev =
								p.sold > 0 ? (p.sold / Math.max(1, s.preHandoverUnits)) * s.preHandoverGDV : 0}
							<td
								class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900"
							>
								{rev > 0 ? fmtK(rev) : '—'}
							</td>
						{/each}
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</div>
