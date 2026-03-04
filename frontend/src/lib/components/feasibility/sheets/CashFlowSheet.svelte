<script lang="ts">
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';

	// Positive cost → show in brackets as outflow; zero → dash
	function outflow(n: number): string {
		if (n <= 0) return '—';
		return `(${Math.round(n / 1000).toLocaleString('en-AE')})`;
	}
	// Positive inflow → show as number; zero → dash
	function inflow(n: number): string {
		if (n <= 0) return '—';
		return Math.round(n / 1000).toLocaleString('en-AE');
	}
	// Net value — brackets for negative, dash for zero
	function fmtK(n: number): string {
		if (n === 0) return '—';
		const k = Math.round(Math.abs(n) / 1000);
		const f = k.toLocaleString('en-AE');
		return n < 0 ? `(${f})` : f;
	}

	const s = $derived(feasibilityStore);
	const cf = $derived(s.cashflow.slice(0, 20));

	const sectionRow = 'bg-slate-800 border-b border-slate-600';
	const sectionCell = 'px-2 py-1.5 text-[10px] font-bold text-white uppercase tracking-wider sticky left-0 bg-slate-800';
</script>

<div class="overflow-auto flex-1">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">AED '000 unless stated</div>
	<table class="border-collapse text-[11px]" style="min-width: max-content;">
		<thead class="sticky top-0 z-10">
			<tr class="bg-slate-100 border-b-2 border-slate-300">
				<th class="border-r border-slate-300 text-left px-2 py-1.5 text-slate-600 font-semibold sticky left-0 bg-slate-100 z-20 w-36">Line Item</th>
				{#each cf as p}
					<th class="border-r border-slate-200 text-right px-1.5 py-1.5 text-slate-600 font-semibold w-14">Q{p.q + 1}</th>
				{/each}
				{#if s.totalQ > 20}
					<th class="border-r border-slate-200 text-center px-2 py-1.5 text-slate-400 font-normal">…</th>
				{/if}
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold w-16">Total</th>
			</tr>
		</thead>
		<tbody>
			<!-- INFLOWS -->
			<tr class="{sectionRow}">
				<td class="{sectionCell}" colspan={cf.length + 3}>Inflows</td>
			</tr>

			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Equity Draw</td>
				{#each cf as p}
					{@const draw = p.q < s.cq ? s.equityRequired / s.cq : 0}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{inflow(draw)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{inflow(s.equityRequired)}</td>
			</tr>

			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Debt Draw</td>
				{#each cf as p}
					{@const draw = p.q < s.cq ? s.debtAmount / s.cq : 0}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{inflow(draw)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{inflow(s.debtAmount)}</td>
			</tr>

			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Sales Revenue</td>
				{#each cf as p}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{inflow(p.revenue)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{inflow(cf.reduce((sum, p) => sum + p.revenue, 0))}</td>
			</tr>

			<!-- OUTFLOWS -->
			<tr class="{sectionRow}">
				<td class="{sectionCell}" colspan={cf.length + 3}>Outflows</td>
			</tr>

			{#each [
				{ label: 'Land', key: 'land' as const },
				{ label: 'Construction', key: 'construction' as const },
				{ label: 'Soft Costs', key: 'soft' as const },
				{ label: 'Selling & Mkt', key: 'marketing' as const },
			] as row}
				<tr class="border-b border-slate-100 hover:bg-slate-50/60">
					<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">{row.label}</td>
					{#each cf as p}
						<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{outflow(p[row.key])}</td>
					{/each}
					{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
					<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{outflow(cf.reduce((sum, p) => sum + p[row.key], 0))}</td>
				</tr>
			{/each}

			<tr class="border-b border-slate-100 hover:bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Interest</td>
				{#each cf as p}
					{@const interest = p.q < s.cq ? (s.debtAmount * s.assumptions.financeRatePct) / 100 / 4 : 0}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{outflow(interest)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900 font-semibold">{outflow(s.totalInterest)}</td>
			</tr>

			<tr class="border-t-2 border-slate-300">
				<td class="border-r border-slate-200 px-2 py-1.5 font-bold text-slate-700 sticky left-0 bg-white">Total Outflows</td>
				{#each cf as p}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right font-semibold tabular-nums text-slate-900">{outflow(p.costs)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">{outflow(cf.reduce((sum, p) => sum + p.costs, 0))}</td>
			</tr>

			<!-- NET & CUMULATIVE -->
			<tr class="{sectionRow}">
				<td class="{sectionCell}" colspan={cf.length + 3}>Summary</td>
			</tr>

			<tr class="border-b border-slate-200">
				<td class="border-r border-slate-200 px-2 py-1.5 font-semibold text-slate-700 sticky left-0 bg-white">Net Cash Flow</td>
				{#each cf as p}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right font-semibold tabular-nums text-slate-900">{fmtK(p.net)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td class="px-2 py-1.5 text-right font-bold tabular-nums text-slate-900">{fmtK(s.grossProfit)}</td>
			</tr>

			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 sticky left-0 bg-white">Cumulative</td>
				{#each cf as p}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">{fmtK(p.cum)}</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td></td>
			</tr>

			<!-- DEBT BALANCE -->
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500 sticky left-0 bg-white">Debt Balance</td>
				{#each cf as p}
					{@const bal = p.q < s.cq ? s.debtAmount * ((p.q + 1) / s.cq) : 0}
					<td class="border-r border-slate-100 px-1.5 py-1.5 text-right tabular-nums text-slate-900">
						{bal > 0 ? Math.round(bal / 1000).toLocaleString('en-AE') : '—'}
					</td>
				{/each}
				{#if s.totalQ > 20}<td class="border-r border-slate-100"></td>{/if}
				<td></td>
			</tr>
		</tbody>
	</table>

	<!-- Summary stats -->
	<div class="flex gap-6 px-3 py-2.5 border-t-2 border-slate-300 bg-slate-50 text-[11px]">
		<div>
			<span class="text-slate-500">Peak Funding:</span>
			<span class="font-semibold text-slate-900 ml-1">{Math.round(s.peakFunding / 1000).toLocaleString('en-AE')}</span>
		</div>
		<div>
			<span class="text-slate-500">Cash Breakeven:</span>
			<span class="font-semibold text-slate-900 ml-1">{s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—'}</span>
		</div>
		<div>
			<span class="text-slate-500">Total Interest:</span>
			<span class="font-semibold text-slate-900 ml-1">{outflow(s.totalInterest)}</span>
		</div>
	</div>
</div>
