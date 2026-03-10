<script lang="ts">
import { feasibilityStore } from '$lib/stores/feasibility.svelte'

interface Props {
	switchTab: (tab: string) => void
}
let { switchTab }: Props = $props()

const s = $derived(feasibilityStore)
const a = $derived(feasibilityStore.assumptions)

function fmtK(n: number): string {
	if (!Number.isFinite(n)) return '—'
	const k = Math.round(Math.abs(n) / 1000)
	const f = k.toLocaleString('en-AE')
	return n < 0 ? `(${f})` : f
}
function fmtPct(n: number): string {
	return !Number.isFinite(n) ? '—' : `${n.toFixed(1)}%`
}
function fmtIRR(n: number): string {
	return !Number.isFinite(n) || Number.isNaN(n) ? '—' : `${(n * 100).toFixed(1)}%`
}
function fmtMx(n: number): string {
	return !Number.isFinite(n) || Number.isNaN(n) ? '—' : `${n.toFixed(2)}x`
}

// Color coding for ROC vs target
function rocClass(roc: number): string {
	const target = a.targetROCPct
	if (roc >= target) return 'text-emerald-700 font-bold'
	if (roc >= target * 0.75) return 'text-amber-600 font-bold'
	return 'text-red-600 font-bold'
}

// Color coding for IRR vs discount rate
function irrClass(irr: number): string {
	const hurdle = a.discountRatePct / 100
	if (irr >= hurdle) return 'text-emerald-700 font-bold'
	if (irr >= hurdle * 0.75) return 'text-amber-600 font-bold'
	return 'text-red-600 font-bold'
}

// Programme milestone labels
function quarterLabel(offsetMonths: number): string {
	if (!a.projectStartDate) return `M${offsetMonths}`
	const d = new Date(a.projectStartDate)
	d.setMonth(d.getMonth() + offsetMonths)
	const q = Math.floor(d.getMonth() / 3) + 1
	return `Q${q} ${d.getFullYear()}`
}

const milestones = $derived([
	{ label: 'Construction Start', month: 0 },
	{ label: 'Sales Launch', month: a.salesLaunchMonth },
	{ label: 'Handover', month: a.constructionMonths },
	{ label: 'Sales End', month: a.salesLaunchMonth + a.salesMonths }
])

// Sources & Uses
const sources = $derived([
	{ label: 'Off-plan Proceeds', value: s.preHandoverGDV },
	{ label: 'Senior Debt', value: s.debtAmount },
	{ label: 'Equity', value: s.equityRequired }
])
const sourcesTotal = $derived(sources.reduce((t, r) => t + r.value, 0))

const uses = $derived([
	{ label: 'Land Acquisition', value: s.totalLandCost },
	{ label: 'Hard Construction', value: s.totalHardCost },
	{ label: 'Soft Costs', value: s.totalSoftCost },
	{ label: 'Sales & Marketing', value: s.totalSalesCost },
	{ label: 'Finance Costs', value: s.totalFinanceCost },
	...(s.vatBridgeLoanInterest > 0
		? [{ label: 'VAT Bridge Loan', value: s.vatBridgeLoanInterest }]
		: [])
])
const usesTotal = $derived(uses.reduce((t, r) => t + r.value, 0))
const balanceOk = $derived(Math.abs(sourcesTotal - usesTotal) < Math.max(usesTotal, 1) * 0.01)

const sectionCell = 'px-2 py-1.5 text-[10px] font-bold text-white uppercase tracking-wider'
</script>

<div class="overflow-auto flex-1 text-[11px]">
	<div class="px-2 py-0.5 text-[10px] text-right text-slate-400 italic border-b border-slate-200">
		AED '000 unless stated
	</div>

	<!-- Section 1.1 — Project Header -->
	<div class="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-slate-200 bg-slate-50">
		<span class="text-xs font-semibold text-slate-700 truncate max-w-[160px]">
			{s.area ?? 'No area selected'}
		</span>
		{#if s.plot}
			<span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-600">
				{s.plot.plot_area_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm
			</span>
		{/if}
		<span class="text-[10px] px-1.5 py-0.5 rounded bg-slate-200 text-slate-600"
			>{s.hbuStudy?.usage ?? s.plotDossier?.inferred_usage ?? 'unknown'}</span
		>
		<div class="flex items-center gap-1 ml-auto flex-shrink-0">
			<!-- AED / USD toggle -->
			<button
				type="button"
				class="text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors
					{s.displayCurrency === 'AED'
					? 'bg-teal-600 text-white border-teal-600'
					: 'bg-white text-slate-500 border-slate-300 hover:border-slate-400'}"
				onclick={() => feasibilityStore.setDisplayCurrency('AED')}>AED</button
			>
			<button
				type="button"
				class="text-[10px] px-1.5 py-0.5 rounded border font-medium transition-colors
					{s.displayCurrency === 'USD'
					? 'bg-teal-600 text-white border-teal-600'
					: 'bg-white text-slate-500 border-slate-300 hover:border-slate-400'}"
				onclick={() => feasibilityStore.setDisplayCurrency('USD')}>USD</button
			>
			<span class="text-[10px] text-slate-400 ml-1">FX</span>
			<input
				type="number"
				class="w-16 text-right text-[10px] px-1 py-0.5 border border-slate-200 rounded bg-amber-50 text-blue-800 focus:outline-none focus:ring-1 focus:ring-teal-400 tabular-nums"
				value={s.fxRateAEDtoUSD}
				step="0.0001"
				min="0.0001"
				oninput={(e) => {
					const v = parseFloat((e.target as HTMLInputElement).value);
					if (v > 0) feasibilityStore.setFxRate(v);
				}}
			/>
		</div>
	</div>

	<!-- Section 1.2 — Key Metrics -->
	<table class="w-full border-collapse">
		<thead>
			<tr class="bg-slate-800 border-b border-slate-600">
				<td
					class="{sectionCell} cursor-pointer hover:text-teal-300"
					onclick={() => switchTab('returns')}
				>
					↗ Key Metrics
				</td>
				<th class="px-2 py-1.5 text-[10px] font-semibold text-slate-300 text-right">Unlevered</th>
				<th class="px-2 py-1.5 text-[10px] font-semibold text-slate-300 text-right">Levered</th>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100 bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500">Total Investment</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-800"
					>{fmtK(s.totalDevCost)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-800">{fmtK(s.equityRequired)}</td>
			</tr>
			<tr class="border-b border-slate-100 bg-slate-50/60">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-500">Net Revenue</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-800"
					>{fmtK(s.totalGDV)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-800">{fmtK(s.netRevenue)}</td>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600 font-medium"
					>Gross Profit</td
				>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900"
					>{fmtK(s.grossProfit)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums font-semibold text-slate-900"
					>{fmtK(s.leveredProfit)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Profit on Cost</td>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums {rocClass(
						s.profitOnCostPct
					)}">{fmtPct(s.profitOnCostPct)}</td
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
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtPct(s.returnOnEquity)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">IRR (annualised)</td>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums {irrClass(
						s.unleveredIRR
					)}">{fmtIRR(s.unleveredIRR)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums {irrClass(s.leveredIRR)}"
					>{fmtIRR(s.leveredIRR)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Equity Multiple</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-300 text-right">—</td>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900">{fmtMx(s.equityMultiple)}</td
				>
			</tr>
			<tr class="border-b border-slate-100">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600"
					>NPV @ {a.discountRatePct}%</td
				>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{fmtK(s.npvUnlevered)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-900"
					>{isFinite(s.npvLevered) ? fmtK(s.npvLevered) : '—'}</td
				>
			</tr>
			<tr class="border-b border-slate-200">
				<td class="border-r border-slate-200 px-2 py-1.5 text-slate-600">Payback</td>
				<td class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums text-slate-900">
					{s.cashBreakevenQuarter >= 0 ? `Q${s.cashBreakevenQuarter + 1}` : '—'}
				</td>
				<td class="px-2 py-1.5 text-slate-300 text-right">—</td>
			</tr>
		</tbody>
	</table>

	<!-- Section 1.3 — Sources & Uses -->
	<div class="bg-slate-800 border-b border-slate-600">
		<div class="{sectionCell} px-2 py-1.5">Sources &amp; Uses ('000)</div>
	</div>
	<div class="flex gap-0 border-b border-slate-200">
		<!-- Sources -->
		<table class="flex-1 border-collapse border-r border-slate-200">
			<thead>
				<tr class="bg-slate-100 border-b border-slate-200">
					<th class="text-left px-2 py-1 text-[10px] text-slate-500 font-semibold">Sources</th>
					<th class="text-right px-2 py-1 text-[10px] text-slate-500 font-semibold">%</th>
					<th class="text-right px-2 py-1 text-[10px] text-slate-500 font-semibold">'000</th>
				</tr>
			</thead>
			<tbody>
				{#each sources as row (row.label)}
					<tr class="border-b border-slate-100">
						<td class="px-2 py-1 text-slate-600">{row.label}</td>
						<td class="px-2 py-1 text-right tabular-nums text-slate-400 text-[10px]"
							>{sourcesTotal > 0 ? ((row.value / sourcesTotal) * 100).toFixed(0) : '—'}%</td
						>
						<td class="px-2 py-1 text-right tabular-nums text-slate-900">{fmtK(row.value)}</td>
					</tr>
				{/each}
				<tr class="border-t-2 border-slate-300">
					<td class="px-2 py-1 font-semibold text-slate-700">Total</td>
					<td class="px-2 py-1 text-right text-[10px] text-slate-400">100%</td>
					<td class="px-2 py-1 text-right font-semibold tabular-nums text-slate-900"
						>{fmtK(sourcesTotal)}</td
					>
				</tr>
			</tbody>
		</table>
		<!-- Uses -->
		<table class="flex-1 border-collapse">
			<thead>
				<tr class="bg-slate-100 border-b border-slate-200">
					<th class="text-left px-2 py-1 text-[10px] text-slate-500 font-semibold">Uses</th>
					<th class="text-right px-2 py-1 text-[10px] text-slate-500 font-semibold">%</th>
					<th class="text-right px-2 py-1 text-[10px] text-slate-500 font-semibold">'000</th>
				</tr>
			</thead>
			<tbody>
				{#each uses as row (row.label)}
					<tr class="border-b border-slate-100">
						<td class="px-2 py-1 text-slate-600">{row.label}</td>
						<td class="px-2 py-1 text-right tabular-nums text-slate-400 text-[10px]"
							>{usesTotal > 0 ? ((row.value / usesTotal) * 100).toFixed(0) : '—'}%</td
						>
						<td class="px-2 py-1 text-right tabular-nums text-slate-900">{fmtK(row.value)}</td>
					</tr>
				{/each}
				<tr class="border-t-2 border-slate-300">
					<td class="px-2 py-1 font-semibold text-slate-700">Total</td>
					<td class="px-2 py-1 text-right text-[10px] text-slate-400">100%</td>
					<td class="px-2 py-1 text-right font-semibold tabular-nums text-slate-900"
						>{fmtK(usesTotal)}</td
					>
				</tr>
				<tr class="{balanceOk ? 'bg-emerald-50' : 'bg-red-50'} border-t border-slate-200">
					<td
						colspan="3"
						class="px-2 py-1 text-[10px] {balanceOk
							? 'text-emerald-700'
							: 'text-red-700'} font-medium text-center"
					>
						{balanceOk
							? '✓ Sources = Uses'
							: `⚠ Gap: ${fmtK(Math.abs(sourcesTotal - usesTotal))} '000`}
					</td>
				</tr>
			</tbody>
		</table>
	</div>

	<!-- Section 1.4 — Programme Timeline -->
	<div class="bg-slate-800 border-b border-slate-600">
		<div
			class="{sectionCell} px-2 py-1.5 cursor-pointer hover:text-teal-300"
			onclick={() => switchTab('schedule')}
		>
			↗ Programme Timeline
		</div>
	</div>
	<div class="px-3 py-3 border-b border-slate-200">
		<div class="flex items-start gap-0">
			{#each milestones as milestone, i (`${milestone.title}-${i}`)}
				<div class="flex-1 flex flex-col items-center gap-1 relative">
					<!-- Connector line (except first) -->
					{#if i > 0}
						<div class="absolute top-2 right-1/2 w-full h-0.5 bg-teal-200 -z-0"></div>
					{/if}
					<div
						class="w-4 h-4 rounded-full bg-teal-500 border-2 border-white ring-1 ring-teal-400 z-10 flex-shrink-0"
					></div>
					<span class="text-[9px] text-slate-500 text-center leading-tight">{milestone.label}</span>
					<span class="text-[9px] font-semibold text-teal-700 text-center"
						>{quarterLabel(milestone.month)}</span
					>
				</div>
			{/each}
		</div>
	</div>

	<!-- Section 1.5 — Scenario Snapshot -->
	<div class="bg-slate-800 border-b border-slate-600">
		<div
			class="{sectionCell} px-2 py-1.5 cursor-pointer hover:text-teal-300"
			onclick={() => switchTab('returns')}
		>
			↗ Scenario Snapshot
		</div>
	</div>
	<table class="w-full border-collapse">
		<thead>
			<tr class="bg-slate-100 border-b border-slate-200">
				<th class="border-r border-slate-200 text-left px-2 py-1.5 text-slate-600 font-semibold"
					>Scenario</th
				>
				<th
					class="border-r border-slate-200 text-left px-2 py-1.5 text-[10px] text-slate-500 font-medium"
					>Assumption</th
				>
				<th class="border-r border-slate-200 text-right px-2 py-1.5 text-slate-600 font-semibold"
					>ROC</th
				>
				<th class="text-right px-2 py-1.5 text-slate-600 font-semibold">Unlev. IRR</th>
			</tr>
		</thead>
		<tbody>
			<tr class="border-b border-slate-100 bg-red-50/40">
				<td class="border-r border-slate-200 px-2 py-1.5 font-medium text-red-700">Stress</td>
				<td class="border-r border-slate-200 px-2 py-1 text-[10px] text-slate-500"
					>−10% price / +10% build cost</td
				>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums {s.stressScenario
						.roc >= a.targetROCPct
						? 'text-emerald-700 font-semibold'
						: s.stressScenario.roc >= a.targetROCPct * 0.75
							? 'text-amber-600 font-semibold'
							: 'text-red-600 font-semibold'}">{fmtPct(s.stressScenario.roc)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-700"
					>{fmtIRR(s.stressScenario.unleveredIRR)}</td
				>
			</tr>
			<tr class="border-b border-slate-100 bg-slate-50">
				<td class="border-r border-slate-200 px-2 py-1.5 font-medium text-slate-700">Base</td>
				<td class="border-r border-slate-200 px-2 py-1 text-[10px] text-slate-500"
					>Current inputs</td
				>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums {rocClass(
						s.baseScenario.roc
					)}">{fmtPct(s.baseScenario.roc)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-700"
					>{fmtIRR(s.baseScenario.unleveredIRR)}</td
				>
			</tr>
			<tr class="border-b border-slate-100 bg-emerald-50/40">
				<td class="border-r border-slate-200 px-2 py-1.5 font-medium text-emerald-700">Upside</td>
				<td class="border-r border-slate-200 px-2 py-1 text-[10px] text-slate-500"
					>+10% price / −5% build cost</td
				>
				<td
					class="border-r border-slate-200 px-2 py-1.5 text-right tabular-nums {s.upsideScenario
						.roc >= a.targetROCPct
						? 'text-emerald-700 font-semibold'
						: s.upsideScenario.roc >= a.targetROCPct * 0.75
							? 'text-amber-600 font-semibold'
							: 'text-red-600 font-semibold'}">{fmtPct(s.upsideScenario.roc)}</td
				>
				<td class="px-2 py-1.5 text-right tabular-nums text-slate-700"
					>{fmtIRR(s.upsideScenario.unleveredIRR)}</td
				>
			</tr>
		</tbody>
	</table>

	<div class="px-3 py-2 text-[10px] text-slate-400 italic">
		Target ROC: {a.targetROCPct}% · Hurdle Rate (NPV): {a.discountRatePct}% ·
		<button
			type="button"
			class="underline hover:text-teal-600 transition-colors"
			onclick={() => switchTab('assumptions')}
		>
			Edit in Assumptions →
		</button>
	</div>
</div>
