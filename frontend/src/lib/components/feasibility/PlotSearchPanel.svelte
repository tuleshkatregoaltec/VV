<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { Plot } from '$lib/api/generated/hey-api/types.gen'
import { feasibilityQueries } from '$lib/queries/feasibility'
import { workbookStore } from '$lib/stores/workbookStore.svelte'

type UsageFilter = 'all' | 'residential' | 'commercial' | 'mixed'
type SortKey = 'verified' | 'largest' | 'highest_gfa'

const communitiesQuery = createQuery(() => feasibilityQueries.communities())

let communitySearch = $state('')
let selectedCommunity = $state('')
let plotSearch = $state('')
let usageFilter = $state<UsageFilter>('all')
let verifiedOnly = $state(false)
let minPlotArea = $state('')
let sortBy = $state<SortKey>('verified')

const pageSize = 100
const communityPlotsQuery = createQuery(() =>
	feasibilityQueries.communityPlots(selectedCommunity || null, pageSize)
)

function inferUsage(plot: Plot): UsageFilter {
	const haystack = `${plot.gfa_type} ${(plot.land_use_summary ?? []).join(' ')}`.toLowerCase()
	const hasResidential = ['residential', 'apartment', 'villa', 'townhouse'].some((token) =>
		haystack.includes(token)
	)
	const hasCommercial = ['commercial', 'office', 'retail', 'hotel', 'industrial'].some((token) =>
		haystack.includes(token)
	)
	if (hasResidential && hasCommercial) return 'mixed'
	if (hasResidential) return 'residential'
	if (hasCommercial) return 'commercial'
	return 'all'
}

const filteredCommunities = $derived(
	(communitiesQuery.data ?? []).filter((community) =>
		community.toLowerCase().includes(communitySearch.trim().toLowerCase())
	)
)

const visiblePlots = $derived.by(() => {
	const plots = communityPlotsQuery.data ?? []
	const q = plotSearch.trim().toLowerCase()
	const minAreaValue = Number(minPlotArea)
	let rows = plots.filter((plot) => {
		if (verifiedOnly && !plot.is_verified) return false
		if (usageFilter !== 'all') {
			const usage = inferUsage(plot)
			if (usageFilter === 'mixed' ? usage !== 'mixed' : usage !== usageFilter) return false
		}
		if (!Number.isNaN(minAreaValue) && minAreaValue > 0 && plot.plot_area_sqm < minAreaValue)
			return false
		if (!q) return true
		return (
			plot.plot_number.toLowerCase().includes(q) ||
			plot.project_name.toLowerCase().includes(q) ||
			plot.community_name.toLowerCase().includes(q)
		)
	})

	rows = [...rows].sort((a, b) => {
		if (sortBy === 'largest') return b.plot_area_sqm - a.plot_area_sqm
		if (sortBy === 'highest_gfa') return b.max_gfa_sqm - a.max_gfa_sqm
		if (a.is_verified !== b.is_verified) return Number(b.is_verified) - Number(a.is_verified)
		return b.max_gfa_sqm - a.max_gfa_sqm
	})

	return rows
})

function loadCommunityPlots(community: string) {
	selectedCommunity = community
}

async function choosePlot(plot: Plot) {
	await workbookStore.selectPlot(plot)
}
</script>

<div class="mx-auto flex h-full w-full max-w-7xl min-h-0 flex-col gap-6 overflow-hidden px-6 py-6">
	<div class="max-w-3xl flex-shrink-0">
		<p class="text-xs font-semibold uppercase tracking-[0.24em] text-slate-400">Feasibility</p>
		<h1 class="mt-2 text-3xl font-semibold text-slate-900">Seed a study directly from the plot</h1>
		<p class="mt-3 text-sm text-slate-600">
			Pick an area, load the community plot inventory, filter it down, then confirm the raw plot facts before generation.
		</p>
	</div>

	<div class="grid min-h-0 flex-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
		<div class="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
			<div class="border-b border-slate-200 px-5 py-4">
				<p class="text-sm font-semibold text-slate-900">Areas</p>
				<p class="mt-1 text-xs text-slate-500">Load all plots in a community first, then filter the inventory.</p>
			</div>
			<div class="p-4">
				<input
					bind:value={communitySearch}
					placeholder="Filter areas"
					class="h-11 w-full rounded-lg border border-slate-300 px-4 text-sm text-slate-900 outline-none transition focus:border-primary"
				/>
			</div>
			<div class="min-h-0 flex-1 overflow-auto border-t border-slate-100">
				{#if communitiesQuery.isPending}
					<p class="px-5 py-8 text-sm text-slate-500">Loading areas…</p>
				{:else if filteredCommunities.length === 0}
					<p class="px-5 py-8 text-sm text-slate-500">No communities match that search.</p>
				{:else}
					{#each filteredCommunities as community}
						<button
							type="button"
							class="flex w-full items-center justify-between border-b border-slate-100 px-5 py-3 text-left transition {selectedCommunity === community ? 'bg-slate-100 text-[var(--color-fg-1)]' : 'hover:bg-slate-50'}"
							onclick={() => void loadCommunityPlots(community)}
						>
							<span class="text-sm font-medium">{community}</span>
							{#if selectedCommunity === community}
								<span class="text-[11px] uppercase tracking-[0.16em]">Loaded</span>
							{/if}
						</button>
					{/each}
				{/if}
			</div>
		</div>

		<div class="flex min-h-0 flex-col overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
			<div class="border-b border-slate-200 px-5 py-4">
				<p class="text-sm font-semibold text-slate-900">Plots</p>
				<p class="mt-1 text-xs text-slate-500">
					{selectedCommunity ? `Showing ${visiblePlots.length} plots in ${selectedCommunity}` : 'Select an area to load its plot inventory.'}
				</p>
			</div>
			<div class="grid gap-3 border-b border-slate-200 p-4 md:grid-cols-2 xl:grid-cols-4">
				<input
					bind:value={plotSearch}
					placeholder="Search loaded plots"
					class="h-11 rounded-lg border border-slate-300 px-4 text-sm text-slate-900 outline-none transition focus:border-primary"
				/>
				<select bind:value={usageFilter} class="h-11 rounded-lg border border-slate-300 px-4 text-sm text-slate-900 outline-none transition focus:border-primary">
					<option value="all">All uses</option>
					<option value="residential">Residential</option>
					<option value="commercial">Commercial</option>
					<option value="mixed">Mixed</option>
				</select>
				<input
					bind:value={minPlotArea}
					type="number"
					min="0"
					placeholder="Min plot area sqm"
					class="h-11 rounded-lg border border-slate-300 px-4 text-sm text-slate-900 outline-none transition focus:border-primary"
				/>
				<select bind:value={sortBy} class="h-11 rounded-lg border border-slate-300 px-4 text-sm text-slate-900 outline-none transition focus:border-primary">
					<option value="verified">Verified first</option>
					<option value="largest">Largest plot</option>
					<option value="highest_gfa">Highest GFA</option>
				</select>
				<label class="flex items-center gap-2 rounded-lg border border-slate-200 px-4 text-sm text-slate-700 md:col-span-2 xl:col-span-4">
					<input bind:checked={verifiedOnly} type="checkbox" class="h-4 w-4 rounded border-slate-300 text-primary" />
					Verified plots only
				</label>
			</div>
			{#if communityPlotsQuery.error}
				<p class="px-5 py-3 text-sm text-rose-600">
					{communityPlotsQuery.error instanceof Error
						? communityPlotsQuery.error.message
						: 'Failed to load plots.'}
				</p>
			{/if}
			<div class="min-h-0 flex-1 overflow-auto">
				{#if communityPlotsQuery.isPending}
					<p class="px-5 py-8 text-sm text-slate-500">Loading plots…</p>
				{:else if visiblePlots.length === 0}
					<p class="px-5 py-8 text-sm text-slate-500">
						{selectedCommunity ? 'No plots match the current filters.' : 'Select an area to load all of its plots.'}
					</p>
				{:else}
					<div class="divide-y divide-slate-100">
						{#each visiblePlots as plot}
							<button
								type="button"
								class="flex w-full flex-col gap-1 px-5 py-4 text-left transition hover:bg-slate-50"
								onclick={() => void choosePlot(plot)}
							>
								<div class="flex items-center justify-between gap-3">
									<span class="text-sm font-semibold text-slate-900">{plot.project_name}</span>
									<div class="flex items-center gap-2">
										{#if plot.is_verified}
											<span class="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-700">
												Verified
											</span>
										{/if}
										<span class="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
											{plot.plot_number}
										</span>
									</div>
								</div>
								<p class="text-sm text-slate-600">{plot.community_name}</p>
								<p class="text-xs text-slate-500">
									{plot.plot_area_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm plot
									· {plot.max_gfa_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm GFA
									· {inferUsage(plot)}
								</p>
							</button>
						{/each}
					</div>
				{/if}
			</div>
		</div>

		<div class="min-h-0 overflow-auto rounded-xl border border-[var(--color-border)] bg-white p-5">
			<p class="text-sm font-semibold text-slate-900">Selected raw plot data</p>
			{#if workbookStore.plotData}
				<div class="mt-4 grid gap-3 text-sm text-slate-600">
					<div>
						<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Project</p>
						<p class="mt-1 font-medium text-slate-900">{workbookStore.plotData.project_name}</p>
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Community</p>
							<p class="mt-1">{workbookStore.plotData.community_name}</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Usage</p>
							<p class="mt-1">{workbookStore.plotData.inferred_usage.replaceAll('_', ' ')}</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Plot Area</p>
							<p class="mt-1">{workbookStore.plotData.plot_area_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Max GFA</p>
							<p class="mt-1">{workbookStore.plotData.max_gfa_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm</p>
						</div>
					</div>
					<button
						type="button"
						class="mt-2 h-11 rounded-lg bg-primary px-4 text-sm font-medium text-white transition hover:bg-primary"
						onclick={() => void workbookStore.generateStudy()}
					>
						Generate Study
					</button>
				</div>
			{:else}
				<p class="mt-4 text-sm text-slate-500">Choose a plot to inspect the raw GIS-backed facts before generation.</p>
			{/if}
			{#if workbookStore.error}
				<p class="mt-3 text-sm text-rose-600">{workbookStore.error}</p>
			{/if}
		</div>
	</div>
</div>
