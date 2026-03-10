<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	function fmtK(n: number): string {
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}
	function fmtPct(n: number): string {
		return isNaN(n) || !isFinite(n) ? '—' : `${n.toFixed(1)}%`;
	}
	function fmtIRR(n: number): string {
		return isNaN(n) || !isFinite(n) ? '—' : `${(n * 100).toFixed(1)}%`;
	}

	type Axis = 'Price/sqm' | 'Build Cost/sqm' | 'Finance Rate' | 'Land Cost';
	const axisOptions: Axis[] = ['Price/sqm', 'Build Cost/sqm', 'Finance Rate', 'Land Cost'];
	let axisX = $state<Axis>('Price/sqm');
	let axisY = $state<Axis>('Build Cost/sqm');

	// 5×5: ±20%, ±10%, base
	const steps = [-0.2, -0.1, 0, 0.1, 0.2];

	const s = $derived(feasibilityStore);

	function financeRateCostDelta(step: number): number {
		const adjDevCost = s.preFinanceCost + s.totalInterest * (1 + step) + s.arrangementFee;
		return s.totalDevCost > 0 ? (adjDevCost - s.totalDevCost) / s.totalDevCost : 0;
	}

	function axisFactors(axis: Axis, step: number): { pa: number; ca: number } {
		switch (axis) {
			case 'Price/sqm':
				return { pa: step, ca: 0 };
			case 'Build Cost/sqm':
				return { pa: 0, ca: step * (s.totalDevCost > 0 ? s.totalHardCost / s.totalDevCost : 0) };
			case 'Finance Rate':
				return { pa: 0, ca: financeRateCostDelta(step) };
			case 'Land Cost':
				return { pa: 0, ca: step * (s.totalDevCost > 0 ? s.totalLandCost / s.totalDevCost : 0) };
		}
	}

	function cellFactors(rowStep: number, colStep: number): { pa: number; ca: number } {
		const row = axisFactors(axisY, rowStep);
		const col = axisFactors(axisX, colStep);
		return { pa: row.pa + col.pa, ca: row.ca + col.ca };
	}

	function rocAtFactors(pa: number, ca: number): number {
		const gdvAdj = s.totalGDV * (1 + pa);
		const devCostAdj = s.totalDevCost * (1 + ca);
		return devCostAdj > 0 ? ((gdvAdj - devCostAdj) / devCostAdj) * 100 : 0;
	}

	function irrAtFactors(pa: number, ca: number): number {
		return s.computeScenario(1 + pa, 1 + ca).unleveredIRR * 100;
	}

	function cellClass(pa: number, ca: number): string {
		const roc = rocAtFactors(pa, ca);
		const target = s.assumptions.targetROCPct;
		if (roc >= target) return 'bg-emerald-50';
		if (roc >= target * 0.75) return 'bg-amber-50';
		return 'bg-red-50';
	}

	function stepLabel(step: number) {
		if (step === 0) return 'Base';
		const sign = step > 0 ? '+' : '';
		return `${sign}${(step * 100).toFixed(0)}%`;
	}

	// ── Tornado chart ─────────────────────────────────────────────────────────
	// Each driver: compute IRR at +10% and -10%, report delta from base
	interface TornadoBar {
		name: string;
		upIRR: number; // IRR at +10% (annualised, decimal)
		downIRR: number; // IRR at -10%
		upDelta: number;
		downDelta: number;
		absMax: number;
	}

	const tornadoBars = $derived(
		(() => {
			const base = s.unleveredIRR;
			if (isNaN(base) || !isFinite(base) || s.totalDevCost === 0) return [] as TornadoBar[];

			const hardFrac = s.totalHardCost / s.totalDevCost;
			const landFrac = s.totalLandCost / s.totalDevCost;
			const softFrac = s.totalSoftCost / s.totalDevCost;
			const salesFrac = s.totalSalesCost / s.totalDevCost;

			const drivers: Array<{ name: string; pa10: number; ca10: number }> = [
				{ name: 'Sale Price / sqm', pa10: 0.1, ca10: 0 },
				{ name: 'Build Cost / sqm', pa10: 0, ca10: hardFrac * 0.1 },
				{ name: 'Land Cost', pa10: 0, ca10: landFrac * 0.1 },
				{ name: 'Soft Costs', pa10: 0, ca10: softFrac * 0.1 },
				{ name: 'Sales & Marketing', pa10: 0, ca10: salesFrac * 0.1 },
				{ name: 'Finance Rate', pa10: 0, ca10: financeRateCostDelta(0.1) }
			];

			const bars: TornadoBar[] = drivers.map((d) => {
				const upIRR = s.computeScenario(1 + d.pa10, 1 + d.ca10).unleveredIRR;
				const downIRR = s.computeScenario(1 - d.pa10, 1 - d.ca10).unleveredIRR;
				const upDelta = isFinite(upIRR) ? upIRR - base : 0;
				const downDelta = isFinite(downIRR) ? downIRR - base : 0;
				return {
					name: d.name,
					upIRR,
					downIRR,
					upDelta,
					downDelta,
					absMax: Math.max(Math.abs(upDelta), Math.abs(downDelta))
				};
			});

			return bars.sort((a, b) => b.absMax - a.absMax);
		})()
	);

	const tornadoScale = $derived(
		tornadoBars.length > 0 ? Math.max(0.001, ...tornadoBars.map((b) => b.absMax)) : 0.001
	);

	const sectionRow = 'bg-slate-800 border-b border-slate-600';
	const sectionCell = 'px-2 py-1.5 text-[10px] font-bold text-white uppercase tracking-wider';
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">
		AED '000 unless stated
	</div>

	<!-- Section A: Returns Summary -->
	<table class="w-full border-collapse">
		<thead>
			<tr class={sectionRow}>
				<td colspan="3" class={sectionCell}>Returns Summary</td>
			</tr>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold"
					>Metric</th
				>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold"
					>Unlevered</th
				>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">Levered</th>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100 bg-green-50">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Total Investment</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtK(s.totalDevCost)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.equityRequired)}</td>
			</tr>
			<tr class="border-b border-slate-100 bg-green-50">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Gross Revenue (GDV)</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtK(s.totalGDV)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtK(s.netRevenue)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Gross Profit</td>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{fmtK(s.grossProfit)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{fmtK(s.leveredProfit)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Net Profit (post-tax)</td>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{fmtK(s.netProfit)}</td
				>
				<td class="px-2 py-1.5 text-slate-300 text-right">—</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Profit on Cost (ROC)</td>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{fmtPct(s.returnOnCost)}</td
				>
				<td class="px-2 py-1.5 text-slate-300 text-right">—</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Profit on GDV</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtPct(s.profitOnGDVPct)}</td
				>
				<td class="px-2 py-1.5 text-slate-300 text-right">—</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Return on Equity</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-300 text-right">—</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{fmtPct(s.returnOnEquity)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Equity Multiple</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-300 text-right">—</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold"
					>{isNaN(s.equityMultiple) ? '—' : `${s.equityMultiple.toFixed(2)}x`}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600"
					>NPV @ {s.assumptions.discountRatePct}%</td
				>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtK(s.npvUnlevered)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{isFinite(s.npvLevered) ? fmtK(s.npvLevered) : '—'}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Cash Payback</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">
					{s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—'}
				</td>
				<td class="px-2 py-1.5 text-slate-300 text-right">—</td>
			</tr>
			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700"
					>IRR (annualised)</td
				>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900"
					>{fmtIRR(s.unleveredIRR)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900"
					>{fmtIRR(s.leveredIRR)}</td
				>
			</tr>
		</tbody>
	</table>

	<!-- Section B: ROC + IRR Sensitivity Heatmap (5×5) -->
	<table class="w-full border-collapse">
		<thead>
			<tr class={sectionRow}>
				<td colspan="7" class={sectionCell}>Sensitivity Heatmap — ROC / Unlevered IRR</td>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 w-24">Rows (Y axis)</td>
				<td colspan="6" class="px-2 py-1.5">
					<select
						bind:value={axisY}
						class="text-[11px] border border-slate-300 rounded px-1.5 py-0.5 bg-white text-slate-700"
					>
						{#each axisOptions.filter((o) => o !== axisX) as opt}
							<option value={opt}>{opt}</option>
						{/each}
					</select>
				</td>
			</tr>
			<tr class="border-b border-slate-200">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Cols (X axis)</td>
				<td colspan="6" class="px-2 py-1.5">
					<select
						bind:value={axisX}
						class="text-[11px] border border-slate-300 rounded px-1.5 py-0.5 bg-white text-slate-700"
					>
						{#each axisOptions.filter((o) => o !== axisY) as opt}
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
				<th
					class="border-r border-slate-200 px-1.5 py-1.5 text-slate-500 font-normal text-left w-20 text-[10px]"
					>↓Y \ X→</th
				>
				{#each steps as cs}
					<th
						class="border-r border-slate-200 px-1.5 py-1.5 text-slate-600 font-semibold text-center text-[10px] {cs ===
						0
							? 'bg-slate-200'
							: ''}">{stepLabel(cs)}</th
					>
				{/each}
			</tr>
		</thead>
		<tbody>
			{#each steps as rs}
				<tr
					class="border-b border-slate-100 {rs === 0
						? 'border-t-2 border-b-2 border-slate-200'
						: ''}"
				>
					<td
						class="border-r border-slate-200 px-1.5 py-1.5 text-slate-600 font-semibold text-[10px] {rs ===
						0
							? 'bg-slate-100'
							: ''}">{stepLabel(rs)}</td
					>
					{#each steps as cs}
						{@const { pa, ca } = cellFactors(rs, cs)}
						{@const roc = rocAtFactors(pa, ca)}
						{@const irr = irrAtFactors(pa, ca)}
						<td
							class="border-r border-slate-100 px-1.5 py-1 text-center {cellClass(pa, ca)} {rs ===
								0 && cs === 0
								? 'ring-2 ring-inset ring-slate-400'
								: ''}"
						>
							<div class="tabular-nums text-[10px] font-semibold leading-tight">{fmtPct(roc)}</div>
							<div class="tabular-nums text-[9px] leading-tight text-slate-500">{fmtIRR(irr)}</div>
						</td>
					{/each}
				</tr>
			{/each}
		</tbody>
	</table>
	<div class="flex gap-4 px-3 py-1.5 text-[10px] text-slate-500 border-b border-slate-200">
		<span class="font-medium text-slate-600">Top: ROC · Bottom: Unlevered IRR</span>
		<span class="flex items-center gap-1"
			><span class="inline-block w-3 h-3 rounded bg-emerald-50 border border-emerald-200"></span> ≥
			target ({s.assumptions.targetROCPct}%)</span
		>
		<span class="flex items-center gap-1"
			><span class="inline-block w-3 h-3 rounded bg-amber-50 border border-amber-200"></span> ≥ 75% of
			target</span
		>
		<span class="flex items-center gap-1"
			><span class="inline-block w-3 h-3 rounded bg-red-50 border border-red-200"></span> below 75% of
			target</span
		>
	</div>

	<!-- Section C: Tornado Chart -->
	{#if tornadoBars.length > 0}
		{@const barH = 18}
		{@const rowH = barH + 6}
		{@const labelW = 120}
		{@const midX = 200}
		{@const barScale = 160}
		{@const svgW = labelW + barScale * 2 + midX - midX + 40}
		{@const svgH = tornadoBars.length * rowH + 24}
		<div class="bg-slate-800 border-b border-slate-600">
			<div class="{sectionCell} px-2 py-1.5">Tornado Chart — ±10% Sensitivity on Unlevered IRR</div>
		</div>
		<div class="px-3 py-3 border-b border-slate-200">
			<svg viewBox="0 0 {svgW} {svgH}" class="w-full" style="max-height: {svgH}px;">
				<!-- Axis labels -->
				<text x={labelW + barScale} y="12" text-anchor="middle" font-size="8" fill="#94a3b8"
					>−10%</text
				>
				<text x={labelW + barScale + 1} y="12" text-anchor="middle" font-size="8" fill="#94a3b8"
					>Base</text
				>
				<text x={labelW + barScale * 2} y="12" text-anchor="middle" font-size="8" fill="#94a3b8"
					>+10%</text
				>
				<!-- Center line -->
				<line
					x1={labelW + barScale}
					y1="16"
					x2={labelW + barScale}
					y2={svgH}
					stroke="#cbd5e1"
					stroke-width="1"
				/>

				{#each tornadoBars as bar, i}
					{@const y = 18 + i * rowH}
					{@const cx = labelW + barScale}
					{@const upW = Math.max(1, (Math.abs(bar.upDelta) / tornadoScale) * barScale * 0.9)}
					{@const downW = Math.max(1, (Math.abs(bar.downDelta) / tornadoScale) * barScale * 0.9)}
					<!-- Driver label -->
					<text x={labelW - 4} y={y + barH / 2 + 3} text-anchor="end" font-size="8.5" fill="#475569"
						>{bar.name}</text
					>
					<!-- Down bar (left of center, red) -->
					<rect x={cx - downW} {y} width={downW} height={barH} fill="#fca5a5" rx="2" />
					<!-- Up bar (right of center, green) -->
					<rect x={cx} {y} width={upW} height={barH} fill="#6ee7b7" rx="2" />
					<!-- Delta labels -->
					<text
						x={cx - downW - 2}
						y={y + barH / 2 + 3}
						text-anchor="end"
						font-size="7.5"
						fill="#b91c1c"
					>
						{bar.downDelta >= 0 ? '+' : ''}{(bar.downDelta * 100).toFixed(1)}pp
					</text>
					<text
						x={cx + upW + 2}
						y={y + barH / 2 + 3}
						text-anchor="start"
						font-size="7.5"
						fill="#047857"
					>
						{bar.upDelta >= 0 ? '+' : ''}{(bar.upDelta * 100).toFixed(1)}pp
					</text>
				{/each}
			</svg>
			<div class="flex gap-4 mt-1 text-[9px] text-slate-500">
				<span class="flex items-center gap-1"
					><span class="inline-block w-3 h-2 rounded" style="background:#6ee7b7"></span>+10% driver
					→ IRR delta</span
				>
				<span class="flex items-center gap-1"
					><span class="inline-block w-3 h-2 rounded" style="background:#fca5a5"></span>−10% driver
					→ IRR delta</span
				>
				<span class="ml-auto text-slate-400">Base IRR: {fmtIRR(s.unleveredIRR)}</span>
			</div>
		</div>
	{/if}
</div>
