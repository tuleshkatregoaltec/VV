<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { feasibility } from '$lib/api/feasibility'
import type { Plot } from '$lib/api/generated/hey-api/types.gen'
import { feasibilityStudy } from '$lib/stores/feasibilityStudy.svelte'

type UsageFilter = 'all' | 'residential' | 'commercial' | 'mixed'
type SortKey = 'verified' | 'largest' | 'highest_gfa'

const communitiesQuery = createQuery(() => ({
	queryKey: ['feasibility-communities'],
	queryFn: () => feasibility.getCommunities(),
	staleTime: Infinity
}))

let communitySearch = $state('')
let selectedCommunity = $state('')
let plotSearch = $state('')
let usageFilter = $state<UsageFilter>('all')
let verifiedOnly = $state(false)
let minPlotArea = $state('')
let loading = $state(false)
let searchError = $state('')
let plots = $state<Plot[]>([])
let sortBy = $state<SortKey>('verified')

const pageSize = 100

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

async function loadCommunityPlots(community: string) {
	selectedCommunity = community
	loading = true
	searchError = ''
	plots = []
	try {
		const allPlots: Plot[] = []
		let offset = 0
		while (true) {
			const page = await feasibility.searchPlots({
				community,
				offset,
				limit: pageSize
			})
			allPlots.push(...page)
			if (page.length < pageSize) break
			offset += page.length
		}
		plots = allPlots
	} catch (error) {
		searchError = error instanceof Error ? error.message : 'Failed to load plots.'
	} finally {
		loading = false
	}
}

async function choosePlot(plot: Plot) {
	await feasibilityStudy.selectPlot(plot)
}
</script>

<div class="mx-auto flex h-full w-full max-w-[1500px] min-h-0 flex-col gap-4 overflow-auto bg-app px-4 py-4 lg:overflow-hidden lg:px-6">
	<div class="flex flex-shrink-0 flex-wrap items-end justify-between gap-3">
		<div class="max-w-3xl">
			<p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Feasibility</p>
			<h1 class="mt-1 text-2xl font-semibold text-slate-900">Seed a study from a plot</h1>
			<p class="mt-2 text-sm text-slate-600">
				Load a community, narrow the plot inventory, then confirm the facts before generation.
			</p>
		</div>
		{#if selectedCommunity}
			<div class="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600 shadow-sm">
				<span class="font-medium text-slate-900">{visiblePlots.length}</span> matching plots in {selectedCommunity}
			</div>
		{/if}
	</div>

	<div class="grid min-h-0 flex-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
		<section class="flex min-h-[560px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm lg:min-h-0">
			<div class="grid gap-3 border-b border-slate-200 p-4 md:grid-cols-[minmax(220px,1fr)_repeat(3,minmax(140px,180px))]">
				<input
					bind:value={plotSearch}
					placeholder="Search loaded plots"
					class="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-900 outline-none transition focus:border-navy focus:ring-2 focus:ring-navy/10"
				/>
				<select bind:value={usageFilter} class="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-900 outline-none transition focus:border-navy focus:ring-2 focus:ring-navy/10">
					<option value="all">All uses</option>
					<option value="residential">Residential</option>
					<option value="commercial">Commercial</option>
					<option value="mixed">Mixed</option>
				</select>
				<input
					bind:value={minPlotArea}
					type="number"
					min="0"
					placeholder="Min area sqm"
					class="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-900 outline-none transition focus:border-navy focus:ring-2 focus:ring-navy/10"
				/>
				<select bind:value={sortBy} class="h-10 rounded-md border border-slate-300 px-3 text-sm text-slate-900 outline-none transition focus:border-navy focus:ring-2 focus:ring-navy/10">
					<option value="verified">Verified first</option>
					<option value="largest">Largest plot</option>
					<option value="highest_gfa">Highest GFA</option>
				</select>
				<label class="flex h-9 items-center gap-2 rounded-md border border-slate-200 px-3 text-sm text-slate-700 md:col-span-4">
					<input bind:checked={verifiedOnly} type="checkbox" class="h-4 w-4 rounded border-slate-300 text-navy" />
					Verified plots only
				</label>
			</div>

			<div class="grid min-h-0 flex-1 lg:grid-cols-[280px_minmax(0,1fr)]">
				<div class="flex min-h-0 flex-col border-b border-slate-200 lg:border-b-0 lg:border-r">
					<div class="border-b border-slate-200 p-4">
						<p class="text-sm font-semibold text-slate-900">Communities</p>
						<input
							bind:value={communitySearch}
							placeholder="Filter communities"
							class="mt-3 h-10 w-full rounded-md border border-slate-300 px-3 text-sm text-slate-900 outline-none transition focus:border-navy focus:ring-2 focus:ring-navy/10"
						/>
					</div>
					<div class="max-h-64 min-h-0 flex-1 overflow-auto lg:max-h-none">
						{#if communitiesQuery.isPending}
							<p class="px-4 py-8 text-sm text-slate-500">Loading communities…</p>
						{:else if filteredCommunities.length === 0}
							<p class="px-4 py-8 text-sm text-slate-500">No communities match that search.</p>
						{:else}
							{#each filteredCommunities as community}
								<button
									type="button"
									class="flex w-full items-center justify-between gap-3 border-b border-slate-100 px-4 py-3 text-left transition {selectedCommunity === community ? 'bg-blue-50 text-navy' : 'hover:bg-slate-50'}"
									onclick={() => void loadCommunityPlots(community)}
								>
									<span class="truncate text-sm font-medium">{community}</span>
									{#if selectedCommunity === community}
										<span class="text-[10px] font-semibold uppercase tracking-[0.12em]">Loaded</span>
									{/if}
								</button>
							{/each}
						{/if}
					</div>
				</div>

				<div class="flex min-h-0 flex-col">
					<div class="flex items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
						<div>
							<p class="text-sm font-semibold text-slate-900">Plots</p>
							<p class="mt-0.5 text-xs text-slate-500">
								{selectedCommunity ? `${visiblePlots.length} results` : 'Select a community to load plots.'}
							</p>
						</div>
					</div>
					{#if searchError}
						<p class="px-4 py-3 text-sm text-rose-600">{searchError}</p>
					{/if}
					<div class="min-h-0 flex-1 overflow-auto">
						{#if loading}
							<p class="px-4 py-8 text-sm text-slate-500">Loading plots…</p>
						{:else if visiblePlots.length === 0}
							<p class="px-4 py-8 text-sm text-slate-500">
								{selectedCommunity ? 'No plots match the current filters.' : 'Select a community to load all of its plots.'}
							</p>
						{:else}
							<div class="divide-y divide-slate-100">
								{#each visiblePlots as plot}
									<button
										type="button"
										class="flex w-full flex-col gap-1 px-4 py-3 text-left transition {feasibilityStudy.plotData?.plot_number === plot.plot_number ? 'bg-blue-50' : 'hover:bg-slate-50'}"
										onclick={() => void choosePlot(plot)}
									>
										<div class="flex items-start justify-between gap-3">
											<span class="text-sm font-semibold text-slate-900">{plot.project_name}</span>
											<div class="flex flex-shrink-0 items-center gap-2">
												{#if plot.is_verified}
													<span class="rounded-md bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-700">
														Verified
													</span>
												{/if}
												<span class="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600">
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
			</div>
		</section>

		<aside class="min-h-0 overflow-auto rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
			<p class="text-sm font-semibold text-slate-900">Selected plot</p>
			{#if feasibilityStudy.plotData}
				<div class="mt-4 grid gap-3 text-sm text-slate-600">
					<div>
						<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Project</p>
						<p class="mt-1 font-medium text-slate-900">{feasibilityStudy.plotData.project_name}</p>
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Community</p>
							<p class="mt-1">{feasibilityStudy.plotData.community_name}</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Usage</p>
							<p class="mt-1">{feasibilityStudy.plotData.inferred_usage.replaceAll('_', ' ')}</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Plot Area</p>
							<p class="mt-1">{feasibilityStudy.plotData.plot_area_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm</p>
						</div>
						<div>
							<p class="text-xs uppercase tracking-[0.18em] text-slate-400">Max GFA</p>
							<p class="mt-1">{feasibilityStudy.plotData.max_gfa_sqm.toLocaleString('en-AE', { maximumFractionDigits: 0 })} sqm</p>
						</div>
					</div>
					{#if feasibilityStudy.developmentModelSelectorVisible}
						<div class="rounded-lg border border-slate-200 bg-slate-50 p-4">
							<div class="flex items-start justify-between gap-3">
								<div>
									<p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Development Model</p>
									<p class="mt-1 text-sm text-slate-700">
										Choose the intended underwriting path for this zoning envelope.
									</p>
								</div>
								</div>
							<div class="mt-4 grid gap-3">
								{#each feasibilityStudy.developmentModelOptions as option (option.id)}
									<button
										type="button"
										class="rounded-md border px-4 py-3 text-left transition {feasibilityStudy.developmentModel === option.id
											? option.available
												? 'border-navy bg-blue-50 shadow-sm'
												: 'border-amber-300 bg-amber-50 shadow-sm'
											: 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}"
										onclick={() => feasibilityStudy.setDevelopmentModel(option.id)}
									>
										<div class="flex items-center justify-between gap-3">
											<div>
												<p class="text-sm font-semibold text-slate-900">{option.label}</p>
												<p class="mt-1 text-[11px] uppercase tracking-[0.14em] text-slate-400">{option.descriptor}</p>
											</div>
											<span class="rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] {option.available ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-500'}">
												{option.available ? 'Live now' : 'Next'}
											</span>
										</div>
										<p class="mt-2 text-sm text-slate-600">{option.description}</p>
									</button>
								{/each}
							</div>
							<p class="mt-3 text-xs {feasibilityStudy.canGenerateSelectedModel ? 'text-slate-500' : 'text-amber-700'}">
								{feasibilityStudy.developmentModelMessage}
							</p>
						</div>
					{/if}
					<button
						type="button"
						class="mt-2 h-11 rounded-md px-4 text-sm font-medium text-bone transition {feasibilityStudy.canGenerateSelectedModel ? 'bg-navy hover:bg-primary-light' : 'bg-slate-300 cursor-not-allowed'}"
						disabled={!feasibilityStudy.canGenerateSelectedModel}
						onclick={() => void feasibilityStudy.generateStudy()}
					>
						Generate Study
					</button>
					{#if import.meta.env.DEV}
						<button
							type="button"
							class="h-11 rounded-md border border-dashed border-slate-300 px-4 text-sm font-medium text-slate-600 transition hover:border-navy hover:text-navy"
							onclick={() => feasibilityStudy.openEmptyWorkbookForDev()}
						>
							Open Empty Workbook
						</button>
					{/if}
				</div>
			{:else}
				<p class="mt-4 text-sm text-slate-500">Choose a plot to inspect the raw GIS-backed facts and generate a workbook.</p>
			{/if}
			{#if feasibilityStudy.error}
				<p class="mt-3 text-sm text-rose-600">{feasibilityStudy.error}</p>
			{/if}
		</aside>
	</div>
</div>
