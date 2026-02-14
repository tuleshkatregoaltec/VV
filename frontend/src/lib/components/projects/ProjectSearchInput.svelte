<script lang="ts">
	import type { ProjectSearchResult } from '$lib/api/projects';

	let {
		allProjects,
		onProjectSelect
	}: {
		allProjects: ProjectSearchResult[];
		onProjectSelect: (projectId: number) => void;
	} = $props();

	let searchQuery = $state('');
	let isFocused = $state(false);
	let showDropdown = $state(false);

	// Client-side filtering - instant results!
	let searchResults = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (query.length < 2) return [];
		return allProjects
			.filter(
				(p) =>
					p.project_name.toLowerCase().includes(query) ||
					p.area_name.toLowerCase().includes(query) ||
					(p.master_project_en && p.master_project_en.toLowerCase().includes(query)) ||
					(p.developer_name && p.developer_name.toLowerCase().includes(query))
			)
			.slice(0, 25);
	});

	function handleInput() {
		showDropdown = searchQuery.trim().length >= 2;
	}

	function selectProject(projectId: number) {
		onProjectSelect(projectId);
		searchQuery = '';
		showDropdown = false;
		isFocused = false;
	}

	function handleFocus() {
		isFocused = true;
		if (searchQuery.trim().length >= 2) showDropdown = true;
	}

	function handleBlur() {
		// Delay to allow click on dropdown item to fire first
		setTimeout(() => {
			showDropdown = false;
			isFocused = false;
		}, 150);
	}
</script>

<div class="w-full">
	<div class="relative">
		<div
			class="relative bg-white border rounded-2xl transition-all duration-200 {isFocused
				? 'border-teal-500 shadow-md'
				: 'border-slate-300 shadow-sm hover:border-slate-400'}"
		>
			<input
				type="text"
				bind:value={searchQuery}
				oninput={handleInput}
				onfocus={handleFocus}
				onblur={handleBlur}
				placeholder="Search projects, areas, developers..."
				class="w-full px-4 py-3 bg-transparent outline-none text-slate-800 placeholder-slate-400 rounded-2xl pr-10 text-sm"
			/>
			<div class="absolute right-3 top-1/2 -translate-y-1/2">
				<svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
				</svg>
			</div>
		</div>

		<!-- Dropdown Results -->
		{#if showDropdown && searchResults.length > 0}
			<!-- onmousedown prevents input blur firing before onclick -->
			<div
				onmousedown={(e) => e.preventDefault()}
				class="absolute z-50 w-full mt-1 bg-white rounded-xl shadow-2xl border border-slate-200 max-h-80 overflow-y-auto"
			>
				{#each searchResults as result}
					<button
						onclick={() => selectProject(result.project_id)}
						class="w-full text-left px-4 py-2.5 hover:bg-teal-50 transition-colors border-b border-slate-100 last:border-b-0"
					>
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<div class="text-sm font-semibold text-slate-900 truncate">{result.project_name}</div>
								<div class="text-xs text-slate-500 mt-0.5 truncate">
									{result.master_project_en || result.area_name}
									{#if result.developer_name}
										· {result.developer_name}
									{/if}
								</div>
							</div>
							<span class="flex-shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-teal-100 text-teal-700 mt-0.5">
								Project
							</span>
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>
