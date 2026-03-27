<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { formatCurrency, formatNumber, titleCase } from '$lib/feasibility/workbook/utils'
import { feasibilityWorkspace } from '$lib/stores/feasibilityWorkspace.svelte'

const context = $derived(workbookStore.study_context)
const research = $derived(workbookStore.research)
const plotData = $derived(workbookStore.plotData)
</script>

{#if workbookStore.phase === 'ready'}
	<div class="space-y-4">
		<div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
			<p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Study Context</p>
			<h2 class="mt-2 text-xl font-semibold text-slate-900">
				{context?.headline ?? '—'}
			</h2>
			<p class="mt-2 text-sm text-slate-600">{context?.positioning ?? '—'}</p>
			<div class="mt-4 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
				<p class="font-medium text-slate-900">Market summary</p>
				<p class="mt-1">{context?.market_summary ?? '—'}</p>
			</div>
			<ul class="mt-4 space-y-2 text-sm text-slate-600">
				{#each context?.summary_points ?? [] as point}
					<li class="rounded-2xl border border-slate-200 px-3 py-2">{point}</li>
				{/each}
			</ul>
		</div>

		<div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
			<p class="text-sm font-semibold text-slate-900">Plot Data</p>
			<div class="mt-4 grid grid-cols-2 gap-3 text-sm">
				<div class="rounded-2xl bg-slate-50 p-3">
					<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Community</p>
					<p class="mt-1 text-slate-900">{plotData?.community_name ?? '—'}</p>
				</div>
				<div class="rounded-2xl bg-slate-50 p-3">
					<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Tier</p>
					<p class="mt-1 text-slate-900">{titleCase(context?.project_tier ?? 'unknown')}</p>
				</div>
				<div class="rounded-2xl bg-slate-50 p-3">
					<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Plot Area</p>
					<p class="mt-1 text-slate-900">{formatNumber(plotData?.plot_area_sqm)} sqm</p>
				</div>
				<div class="rounded-2xl bg-slate-50 p-3">
					<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Max GFA</p>
					<p class="mt-1 text-slate-900">{formatNumber(plotData?.max_gfa_sqm)} sqm</p>
				</div>
			</div>
		</div>

		<div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm">
			<div class="flex items-center justify-between gap-3">
				<p class="text-sm font-semibold text-slate-900">Research Snapshot</p>
				<button
					type="button"
					class="text-xs font-medium text-teal-700"
					onclick={() => workbookStore.setActiveSheet('pricing_evidence')}
				>
					Open pricing evidence
				</button>
			</div>
			<div class="mt-4 text-sm text-slate-600">
				<p>Land cost mid estimate: AED {formatCurrency(research?.land_cost_estimate_aed_mid)}</p>
				<p class="mt-1">Pricing comparables: {research?.pricing_evidence?.length ?? 0}</p>
				<p class="mt-1">Land sales: {research?.land_sales_evidence?.length ?? 0}</p>
			</div>
			{#if feasibilityWorkspace.latestResearchEvent}
				<div class="mt-4 rounded-2xl border border-sky-200 bg-sky-50 p-4 text-sm text-sky-800">
					<p class="font-medium">Latest chat research action: {feasibilityWorkspace.latestResearchEvent.tab}</p>
				</div>
			{/if}
		</div>
	</div>
{/if}
