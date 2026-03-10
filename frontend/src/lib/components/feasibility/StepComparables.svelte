<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { projects as projectsAPI } from '$lib/api/projects';
	import { feasibility } from '$lib/api/feasibility';
	import type { ComparableData } from '$lib/stores/feasibility.svelte';
	import type { ProjectSearchResult } from '$lib/api/projects';

	let {
		onApply
	}: {
		onApply: (data: ComparableData) => void;
	} = $props();

	let selected = $state<ProjectSearchResult[]>([]);
	let search = $state('');
	let isOpen = $state(false);
	let loading = $state(false);

	const allQuery = createQuery<ProjectSearchResult[]>(() => ({
		queryKey: ['projects-list'],
		queryFn: () => projectsAPI.list(),
		staleTime: Infinity
	}));

	const filtered = $derived(
		search.trim()
			? (allQuery.data ?? [])
					.filter((p) => p.project_name.toLowerCase().includes(search.toLowerCase()))
					.slice(0, 60)
			: (allQuery.data ?? []).slice(0, 60)
	);

	function toggleSelect(p: ProjectSearchResult) {
		const idx = selected.findIndex((s) => s.project_id === p.project_id);
		if (idx >= 0) {
			selected = selected.filter((_, i) => i !== idx);
		} else {
			selected = [...selected, p];
		}
	}

	function remove(id: number) {
		selected = selected.filter((p) => p.project_id !== id);
	}

	async function apply() {
		if (selected.length === 0) return;
		loading = true;
		try {
			const data = await feasibility.getComparableData(selected.map((p) => p.project_id));
			onApply(data);
		} finally {
			loading = false;
		}
	}

	function clickOutside(node: HTMLElement, cb: () => void) {
		function handle(e: MouseEvent) {
			if (!node.contains(e.target as Node)) cb();
		}
		document.addEventListener('mousedown', handle, true);
		return {
			destroy() {
				document.removeEventListener('mousedown', handle, true);
			}
		};
	}
</script>

<div class="max-w-xl mx-auto">
	<h2 class="text-xl font-semibold text-slate-800 mb-1">Select comparable projects</h2>
	<p class="text-sm text-slate-500 mb-6">
		Pick 1–5 similar projects to seed your unit mix and pricing assumptions.
	</p>

	<!-- Search input -->
	<div class="relative mb-4" use:clickOutside={() => (isOpen = false)}>
		<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
			<svg class="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
				/>
			</svg>
		</div>
		<input
			type="text"
			class="w-full pl-9 pr-4 py-3 rounded-xl border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
			placeholder="Search projects..."
			bind:value={search}
			oninput={() => (isOpen = true)}
			onfocus={() => (isOpen = true)}
		/>
		{#if isOpen}
			<div
				class="absolute z-50 mt-1 w-full max-h-60 overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-lg"
			>
				{#if allQuery.isPending}
					<div class="px-4 py-3 text-sm text-slate-400">Loading projects...</div>
				{:else if filtered.length === 0}
					<div class="px-4 py-3 text-sm text-slate-400">No projects found</div>
				{:else}
					{#each filtered as p}
						{@const isSelected = selected.some((s) => s.project_id === p.project_id)}
						<button
							type="button"
							class="w-full text-left px-4 py-2.5 text-sm transition-colors flex items-center justify-between
								{isSelected ? 'bg-teal-50 text-teal-700' : 'text-slate-900 hover:bg-slate-50'}"
							onmousedown={() => toggleSelect(p)}
						>
							<span>
								<span class="font-medium">{p.project_name}</span>
								<span class="text-slate-400 ml-2">{p.area_name}</span>
							</span>
							{#if isSelected}
								<svg
									class="w-4 h-4 text-teal-500 flex-shrink-0"
									fill="none"
									viewBox="0 0 24 24"
									stroke="currentColor"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2.5"
										d="M5 13l4 4L19 7"
									/>
								</svg>
							{/if}
						</button>
					{/each}
				{/if}
			</div>
		{/if}
	</div>

	<!-- Selected chips -->
	{#if selected.length > 0}
		<div class="flex flex-wrap gap-2 mb-6">
			{#each selected as p}
				<span
					class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-teal-100 text-teal-800 text-sm font-medium"
				>
					{p.project_name}
					<button
						type="button"
						onclick={() => remove(p.project_id)}
						class="text-teal-500 hover:text-teal-700"
					>
						<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							/>
						</svg>
					</button>
				</span>
			{/each}
		</div>
	{/if}

	<button
		type="button"
		class="w-full py-3 rounded-xl bg-teal-600 text-white font-medium text-sm hover:bg-teal-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
		onclick={apply}
		disabled={selected.length === 0 || loading}
	>
		{#if loading}
			<div
				class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"
			></div>
			Analysing comparables...
		{:else}
			Use {selected.length} comparable{selected.length !== 1 ? 's' : ''} →
		{/if}
	</button>
</div>
