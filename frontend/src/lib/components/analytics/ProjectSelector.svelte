<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { analytics, type ProjectSearchItem } from '$lib/api/analytics';

	let {
		value = $bindable<ProjectSearchItem | null>(null),
		placeholder = 'Search project...',
		onSelect
	}: {
		value?: ProjectSearchItem | null;
		placeholder?: string;
		onSelect?: (project: ProjectSearchItem | null) => void;
	} = $props();

	let inputValue = $state(value?.name ?? '');
	let isOpen = $state(false);

	function clickOutside(node: HTMLElement, callback: () => void) {
		function handle(e: MouseEvent) {
			if (!node.contains(e.target as Node)) callback();
		}
		document.addEventListener('mousedown', handle, true);
		return { destroy() { document.removeEventListener('mousedown', handle, true); } };
	}

	// Load all projects once — master projects + standalone orphans
	const allProjectsQuery = createQuery(() => ({
		queryKey: ['project-search-all'],
		queryFn: () => analytics.projectSearch('', 500),
		staleTime: Infinity
	}));

	const allProjects = $derived(allProjectsQuery.data?.projects ?? []);

	const filtered = $derived(
		inputValue.trim() && inputValue !== value?.name
			? allProjects.filter(p => p.name.toLowerCase().includes(inputValue.toLowerCase()))
			: allProjects
	);

	function select(project: ProjectSearchItem) {
		value = project;
		inputValue = project.name;
		isOpen = false;
		onSelect?.(project);
	}

	function clear() {
		value = null;
		inputValue = '';
		isOpen = false;
		onSelect?.(null);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') { isOpen = false; }
		if (e.key === 'Enter') {
			e.preventDefault();
			if (filtered.length > 0) select(filtered[0]);
		}
	}
</script>

<div class="relative" use:clickOutside={() => (isOpen = false)}>
	<div class="relative">
		<div class="pointer-events-none absolute inset-y-0 left-3 flex items-center">
			<svg class="w-4 h-4 text-slate-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
			</svg>
		</div>
		<input
			type="text"
			class="w-full pl-9 pr-8 py-2.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-teal-500 transition-all"
			{placeholder}
			bind:value={inputValue}
			oninput={() => (isOpen = true)}
			onfocus={() => (isOpen = true)}
			onkeydown={handleKeydown}
		/>
		{#if value}
			<button
				type="button"
				class="absolute inset-y-0 right-2 flex items-center px-1 text-slate-400 hover:text-slate-600"
				onclick={clear}
				aria-label="Clear selection"
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		{/if}
	</div>

	{#if isOpen}
		<div class="absolute z-50 mt-1 w-full max-h-72 overflow-y-auto rounded-lg border border-slate-200 bg-white shadow-lg">
			{#if allProjectsQuery.isLoading}
				<div class="px-4 py-3 text-sm text-slate-400">Loading...</div>
			{:else if filtered.length === 0}
				<div class="px-4 py-3 text-sm text-slate-400">No projects found</div>
			{:else}
				{#each filtered as project}
					<button
						type="button"
						class="w-full text-left px-4 py-2.5 text-sm hover:bg-teal-50 transition-colors {project.name === value?.name ? 'bg-teal-50 text-teal-700 font-medium' : 'text-slate-900'}"
						onmousedown={() => select(project)}
					>
						{project.name}
					</button>
				{/each}
			{/if}
		</div>
	{/if}
</div>
