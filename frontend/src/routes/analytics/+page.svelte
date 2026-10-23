<script lang="ts">
import { Building2, GitCompare } from 'lucide-svelte'
import type { ProjectSearchItem } from '$lib/api/analytics'
import AnalyticsCompareView from '$lib/components/analytics/AnalyticsCompareView.svelte'
import ProjectPanel from '$lib/components/analytics/ProjectPanel.svelte'
import ProjectSelector from '$lib/components/analytics/ProjectSelector.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'

const DUBAI_MARKET_SELECTION: ProjectSearchItem = { name: 'Dubai', filter_type: 'market' }

let projectA = $state<ProjectSearchItem | null>({ ...DUBAI_MARKET_SELECTION })
let projectB = $state<ProjectSearchItem | null>(null)
let comparing = $state(false)
let isDubaiMarketSelected = $derived(projectA?.filter_type === 'market')

function toggleCompare() {
	comparing = !comparing
	if (!comparing) projectB = null
}

function selectDubaiMarket() {
	projectA = { ...DUBAI_MARKET_SELECTION }
}
</script>

<PageContainer variant="standard" class="gap-4">
		<section class="ui-surface relative z-30 overflow-visible">
			<div class="ui-page-header grid px-5 py-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-center">
				<div>
					<p class="text-xs font-semibold uppercase tracking-[0.18em] text-on-navy-muted">
						Analytics
					</p>
					<h1 class="mt-1 font-display text-2xl leading-tight tracking-[var(--tracking-display)] text-bone">
						Dubai market analytics
					</h1>
				</div>

				<button
					type="button"
					onclick={toggleCompare}
					data-variant={comparing ? 'primary' : 'secondary'}
					class="ui-button h-10 px-4 text-sm"
				>
					<GitCompare size={16} strokeWidth={1.8} />
					{comparing ? 'Exit compare' : 'Compare'}
				</button>
			</div>
		</section>

		<section class="ui-surface p-4 sm:p-5">
			<div class="mb-4 flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
				<div>
					<p class="text-xs font-semibold uppercase tracking-[0.18em] text-fg-4">
						Project scope
					</p>
					<p class="mt-1 text-sm text-fg-3">
						DXBI sales and rentals. Search a project, building or community. Upcoming supply uses DLD.
					</p>
				</div>
				<button
					type="button"
					onclick={selectDubaiMarket}
					data-variant={isDubaiMarketSelected ? 'primary' : 'secondary'}
					class="ui-button h-9 px-3 text-sm"
				>
					<Building2 size={15} strokeWidth={1.8} />
					Dubai market
				</button>
			</div>
			<div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
				<div class="flex-1">
					<div class="grid gap-3 {comparing ? 'xl:grid-cols-2' : ''}">
						<ProjectSelector bind:value={projectA} label="Project A" />
						{#if comparing}
							<ProjectSelector bind:value={projectB} label="Project B" />
						{/if}
					</div>
				</div>

				<div class="hidden xl:block"></div>
			</div>
		</section>

		{#if comparing}
			{#if projectA && projectB}
				<AnalyticsCompareView {projectA} {projectB} />
			{:else if projectA || projectB}
				<!-- One side chosen: its figures show at once; only the empty side asks for a pick. -->
				{@const chosen = (projectA ?? projectB)!}
				<div class="rounded-lg border border-dashed border-strong bg-card px-5 py-4 text-sm text-fg-3">
					<span class="font-semibold text-fg-1">{chosen.name}</span> is Project {projectA ? 'A' : 'B'}.
					Search for Project {projectA ? 'B' : 'A'} above to compare the two side by side.
				</div>
				<ProjectPanel selection={chosen} onSelect={(next) => (projectA ? (projectA = next) : (projectB = next))} />
			{:else}
				{@render EmptyState('Compare')}
			{/if}
		{:else if projectA}
			<ProjectPanel selection={projectA} onSelect={(next) => (projectA = next)} />
		{:else}
			{@render EmptyState('Analytics')}
		{/if}
</PageContainer>

{#snippet EmptyState(label: string)}
	<div class="rounded-lg border border-dashed border-strong bg-card px-8 py-20 text-center shadow-sm">
		<div class="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-md bg-navy-pale text-primary-light">
			<Building2 size={28} strokeWidth={1.5} />
		</div>
		<p class="text-base font-semibold text-fg-1">{label} is waiting for a project.</p>
		<p class="mt-2 text-sm text-fg-4">Search above to load live transaction-backed analytics.</p>
	</div>
{/snippet}
