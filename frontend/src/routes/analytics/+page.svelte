<script lang="ts">
	import ProjectSelector from '$lib/components/analytics/ProjectSelector.svelte';
	import ProjectPanel from '$lib/components/analytics/ProjectPanel.svelte';
	import type { ProjectSearchItem } from '$lib/api/analytics';

	let projectA = $state<ProjectSearchItem | null>(null);
	let projectB = $state<ProjectSearchItem | null>(null);
	let comparing = $state(false);

	function toggleCompare() {
		comparing = !comparing;
		if (!comparing) projectB = null;
	}
</script>

<div class="min-h-screen bg-slate-50">
	<div class="max-w-7xl mx-auto px-4 py-6">
		<!-- Toolbar -->
		<div class="flex items-center gap-3 mb-6">
			{#if comparing}
				<div class="flex-1 grid grid-cols-2 gap-3">
					<ProjectSelector bind:value={projectA} placeholder="Search project A..." />
					<ProjectSelector bind:value={projectB} placeholder="Search project B..." />
				</div>
			{:else}
				<div class="flex-1 max-w-sm">
					<ProjectSelector bind:value={projectA} placeholder="Search a project..." />
				</div>
			{/if}

			<button
				onclick={toggleCompare}
				class="flex-shrink-0 flex items-center gap-1.5 px-3 py-2.5 rounded-lg border text-sm font-medium transition-colors
					{comparing
					? 'bg-teal-600 border-teal-600 text-white hover:bg-teal-700'
					: 'bg-white border-slate-200 text-slate-600 hover:border-teal-400 hover:text-teal-600'}"
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"
					/>
				</svg>
				Compare
			</button>
		</div>

		<!-- Content -->
		{#if comparing}
			<div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
				<div>
					{#if projectA}
						<ProjectPanel selection={projectA} />
					{:else}
						{@render EmptyState()}
					{/if}
				</div>
				<div>
					{#if projectB}
						<ProjectPanel selection={projectB} />
					{:else}
						{@render EmptyState()}
					{/if}
				</div>
			</div>
		{:else if projectA}
			<ProjectPanel selection={projectA} />
		{:else}
			{@render EmptyState()}
		{/if}
	</div>
</div>

{#snippet EmptyState()}
	<div class="flex flex-col items-center justify-center py-24 text-center">
		<div class="w-14 h-14 rounded-2xl bg-teal-50 flex items-center justify-center mb-4">
			<svg class="w-7 h-7 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="1.5"
					d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
				/>
			</svg>
		</div>
		<p class="text-slate-700 font-medium mb-1">Search for a project</p>
		<p class="text-sm text-slate-400">Type a project name above to view its analytics</p>
	</div>
{/snippet}
