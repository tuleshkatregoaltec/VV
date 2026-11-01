<script lang="ts">
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { formatCurrency, formatNumber, titleCase } from '$lib/feasibility/workbook/utils'
import { type ResearchTab, researchPanelStore } from '$lib/stores/researchPanel.svelte'
import { toSqft } from '$lib/utils/units'
import PlotAnnotationSandbox from './PlotAnnotationSandbox.svelte'

const context = $derived(workbookStore.study_context)
const research = $derived(workbookStore.research)
const plotData = $derived(workbookStore.plotData)

const tabs: Array<{ id: ResearchTab; label: string }> = [
	{ id: 'summary', label: 'Context' },
	{ id: 'comparables', label: 'Research' },
	{ id: 'plot_sandbox', label: 'Plot sandbox' }
]
</script>

{#if workbookStore.phase === 'ready'}
	<div class="space-y-4">
		<div class="sticky top-0 z-10 rounded-lg border border-slate-200 bg-white/95 p-1.5 shadow-sm backdrop-blur">
			<div class="grid grid-cols-3 gap-1">
				{#each tabs as tab (tab.id)}
					<button
						type="button"
						class="rounded-md px-3 py-2 text-xs font-semibold transition {researchPanelStore.activeTab === tab.id ? 'bg-navy text-bone shadow-sm' : 'text-slate-500 hover:bg-slate-100 hover:text-slate-900'}"
						onclick={() => researchPanelStore.setActiveTab(tab.id)}
					>
						{tab.label}
					</button>
				{/each}
			</div>
		</div>

		{#if researchPanelStore.activeTab === 'summary'}
			<div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
				<p class="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">Study context</p>
				<h2 class="mt-2 text-xl font-semibold text-slate-900">
					{context?.headline ?? '—'}
				</h2>
				<p class="mt-2 text-sm text-slate-600">{context?.positioning ?? '—'}</p>
				<div class="mt-4 rounded-md bg-slate-50 p-4 text-sm text-slate-600">
					<p class="font-medium text-slate-900">Market summary</p>
					<p class="mt-1">{context?.market_summary ?? '—'}</p>
				</div>
				<ul class="mt-4 space-y-2 text-sm text-slate-600">
					{#each context?.summary_points ?? [] as point}
						<li class="rounded-md border border-slate-200 px-3 py-2">{point}</li>
					{/each}
				</ul>
			</div>

			<div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
				<p class="text-sm font-semibold text-slate-900">Plot data</p>
				<div class="mt-4 grid grid-cols-2 gap-3 text-sm">
					<div class="rounded-md bg-slate-50 p-3">
						<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Community</p>
						<p class="mt-1 text-slate-900">{plotData?.community_name ?? '—'}</p>
					</div>
					<div class="rounded-md bg-slate-50 p-3">
						<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Tier</p>
						<p class="mt-1 text-slate-900">{titleCase(context?.project_tier ?? 'unknown')}</p>
					</div>
					<div class="rounded-md bg-slate-50 p-3">
						<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Plot area</p>
						<p class="mt-1 text-slate-900">{formatNumber(plotData?.plot_area_sqm == null ? null : toSqft(plotData.plot_area_sqm))} sq ft</p>
					</div>
					<div class="rounded-md bg-slate-50 p-3">
						<p class="text-xs uppercase tracking-[0.16em] text-slate-400">Max GFA</p>
						<p class="mt-1 text-slate-900">{formatNumber(plotData?.max_gfa_sqm == null ? null : toSqft(plotData.max_gfa_sqm))} sq ft</p>
					</div>
				</div>
			</div>
		{:else if researchPanelStore.activeTab === 'plot_sandbox'}
			<PlotAnnotationSandbox />
		{:else}
			<div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
				<div class="flex items-center justify-between gap-3">
					<p class="text-sm font-semibold text-slate-900">Research summary</p>
					<button
						type="button"
						class="text-xs font-medium text-navy underline-offset-2 hover:underline"
						onclick={() => workbookStore.setActiveSheet('pricing_evidence')}
					>
						Open pricing evidence
					</button>
				</div>
				<div class="mt-4 text-sm text-slate-600">
					<p>Land cost mid estimate: AED {formatCurrency(research?.land_cost_estimate_aed_mid)}</p>
					<p class="mt-1">Pricing comparables: {research?.pricing_evidence?.length ?? 0}</p>
					<p class="mt-1">Land sales: {research?.land_sales_evidence?.length ?? 0}</p>
					<p class="mt-1">Rental comparables: {research?.rental_comparables?.length ?? 0}</p>
				</div>
			</div>

			<div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
				<p class="text-sm font-semibold text-slate-900">Flags</p>
				<div class="mt-4 space-y-2 text-sm text-slate-600">
					{#if (research?.constraints?.length ?? 0) === 0 && (research?.warnings?.length ?? 0) === 0}
						<p>No flags.</p>
					{:else}
						{#each research?.constraints ?? [] as item}
							<p class="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-amber-800">{item}</p>
						{/each}
						{#each research?.warnings ?? [] as item}
							<p class="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-rose-800">{item}</p>
						{/each}
					{/if}
				</div>
			</div>
		{/if}
	</div>
{/if}
