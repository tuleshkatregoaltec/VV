<script lang="ts">
import { onMount } from 'svelte'
import type { ProjectSearchItem } from '$lib/api/analytics'
import type { ProjectSearchResult, SearchSelection } from '$lib/api/projects'
import { projects as projectsAPI } from '$lib/api/projects'
import ProjectPanel from '$lib/components/analytics/ProjectPanel.svelte'
import ProjectSearchInput from '$lib/components/projects/ProjectSearchInput.svelte'

let projectA = $state<ProjectSearchItem | null>(null)
let projectB = $state<ProjectSearchItem | null>(null)
let comparing = $state(false)
let allProjects = $state<ProjectSearchResult[]>([])

onMount(async () => {
	try {
		allProjects = await projectsAPI.list()
	} catch (error) {
		console.error('Failed to load analytics project search list:', error)
	}
})

function toggleCompare() {
	comparing = !comparing
	if (!comparing) projectB = null
}

function toAnalyticsSelection(sel: SearchSelection): ProjectSearchItem | null {
	if (sel.type === 'master') {
		return { name: sel.masterName, filter_type: 'master' }
	}

	const project = allProjects.find((item) => item.project_id === sel.projectId)
	if (!project) return null
	return { name: project.project_name, filter_type: 'project' }
}

function handleSearchSelectA(sel: SearchSelection) {
	projectA = toAnalyticsSelection(sel)
}

function handleSearchSelectB(sel: SearchSelection) {
	projectB = toAnalyticsSelection(sel)
}
</script>

<div class="min-h-screen bg-[radial-gradient(circle_at_top,#e6fbf7_0,#f4f7f8_28%,#eef2f5_60%,#e9edf2_100%)]">
	<div class="mx-auto flex w-full max-w-[1480px] flex-col gap-6 px-4 py-6 sm:px-6 lg:px-8">
		<section class="overflow-hidden rounded-[28px] border border-white/60 bg-[linear-gradient(135deg,rgba(7,20,32,0.97)_0%,rgba(8,35,48,0.95)_55%,rgba(6,26,36,0.98)_100%)] px-6 py-6 text-white shadow-[0_30px_90px_-40px_rgba(15,23,42,0.6)]">
			<div class="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
				<div class="max-w-3xl">
					<p class="text-[11px] font-semibold uppercase tracking-[0.28em] text-teal-200/70">Analytics Workspace</p>
					<h1 class="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">Market analytics, redesigned around actual signal.</h1>
					<p class="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
						Search a project or compare two schemes side by side. This view stays grounded in current transaction and rental coverage, and leaves unsupported metrics blank instead of inventing them.
					</p>
				</div>

				<div class="grid min-w-[280px] grid-cols-2 gap-3 sm:grid-cols-3 xl:w-[420px]">
					<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur-sm">
						<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Mode</p>
						<p class="mt-2 text-sm font-semibold text-white">{comparing ? 'Comparison' : 'Single project'}</p>
					</div>
					<div class="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 backdrop-blur-sm">
						<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Loaded</p>
						<p class="mt-2 text-sm font-semibold text-white">{[projectA, projectB].filter(Boolean).length} panel{[projectA, projectB].filter(Boolean).length === 1 ? '' : 's'}</p>
					</div>
					<div class="rounded-2xl border border-teal-400/20 bg-teal-400/10 px-4 py-3 backdrop-blur-sm sm:col-span-2 xl:col-span-1">
						<p class="text-[11px] uppercase tracking-[0.18em] text-teal-100/70">Coverage policy</p>
						<p class="mt-2 text-sm font-semibold text-teal-50">Null over noise</p>
					</div>
				</div>
			</div>
		</section>

		<section class="rounded-[28px] border border-slate-200/70 bg-white/90 p-4 shadow-[0_30px_80px_-50px_rgba(15,23,42,0.28)] backdrop-blur-sm sm:p-5">
			<div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
				<div class="flex-1">
					<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-slate-400">Selection</p>
					<div class="mt-3 grid gap-3 {comparing ? 'xl:grid-cols-2' : 'max-w-xl'}">
						<ProjectSearchInput allProjects={allProjects} onSelect={handleSearchSelectA} />
						{#if comparing}
							<ProjectSearchInput allProjects={allProjects} onSelect={handleSearchSelectB} />
						{/if}
					</div>
				</div>

				<div class="flex items-center gap-3">
					<button
						type="button"
						onclick={toggleCompare}
						class="inline-flex items-center gap-2 rounded-2xl border px-4 py-3 text-sm font-medium transition-colors {comparing
							? 'border-teal-600 bg-teal-600 text-white hover:bg-teal-700'
							: 'border-slate-200 bg-white text-slate-700 hover:border-teal-400 hover:text-teal-700'}"
					>
						<svg class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
						</svg>
						{comparing ? 'Exit compare' : 'Compare'}
					</button>
				</div>
			</div>
		</section>

		{#if comparing && projectA && projectB}
			<section class="rounded-[28px] border border-teal-200/70 bg-[linear-gradient(135deg,rgba(240,253,250,0.95)_0%,rgba(248,250,252,0.92)_100%)] px-5 py-4 shadow-[0_26px_70px_-55px_rgba(15,23,42,0.3)]">
				<div class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
					<div>
						<p class="text-[11px] font-semibold uppercase tracking-[0.22em] text-teal-700/70">Compare mode</p>
						<h2 class="mt-2 text-lg font-semibold text-slate-900">{projectA.name} vs {projectB.name}</h2>
						<p class="mt-1 text-sm text-slate-600">
							Both panels use the same live analytics endpoints so pricing, yield, and mix differences stay comparable.
						</p>
					</div>

					<div class="grid gap-3 sm:grid-cols-3">
						<div class="rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
							<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Project A</p>
							<p class="mt-2 text-sm font-semibold text-slate-900">{projectA.filter_type}</p>
						</div>
						<div class="rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
							<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Project B</p>
							<p class="mt-2 text-sm font-semibold text-slate-900">{projectB.filter_type}</p>
						</div>
						<div class="rounded-2xl border border-white/70 bg-white/80 px-4 py-3">
							<p class="text-[11px] uppercase tracking-[0.18em] text-slate-400">Method</p>
							<p class="mt-2 text-sm font-semibold text-slate-900">Actual signals only</p>
						</div>
					</div>
				</div>
			</section>
		{/if}

		{#if comparing}
			<div class="grid grid-cols-1 gap-6 xl:grid-cols-2">
				<div>
					{#if projectA}
						<ProjectPanel selection={projectA} />
					{:else}
						{@render EmptyState('Project A')}
					{/if}
				</div>
				<div>
					{#if projectB}
						<ProjectPanel selection={projectB} />
					{:else}
						{@render EmptyState('Project B')}
					{/if}
				</div>
			</div>
		{:else if projectA}
			<ProjectPanel selection={projectA} />
		{:else}
			{@render EmptyState('Analytics')}
		{/if}
	</div>
</div>

{#snippet EmptyState(label: string)}
	<div class="rounded-[28px] border border-dashed border-slate-300 bg-white/85 px-8 py-20 text-center shadow-[0_25px_70px_-55px_rgba(15,23,42,0.35)]">
		<div class="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-3xl bg-teal-50">
			<svg class="h-8 w-8 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
			</svg>
		</div>
		<p class="text-base font-semibold text-slate-800">{label} is waiting for a project.</p>
		<p class="mt-2 text-sm text-slate-500">Search above to load live transaction-backed analytics.</p>
	</div>
{/snippet}
