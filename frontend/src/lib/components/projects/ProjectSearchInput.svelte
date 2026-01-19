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
	let searchResults = $derived(() => {
		const query = searchQuery.trim().toLowerCase();

		if (query.length < 2) {
			return [];
		}

		return allProjects
			.filter(
				(p) =>
					p.project_name.toLowerCase().includes(query) ||
					p.area_name.toLowerCase().includes(query) ||
					(p.developer_name && p.developer_name.toLowerCase().includes(query))
			)
			.slice(0, 20); // Limit to 20 results for performance
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
	}

	function handleBlur() {
		// Delay to allow click on dropdown
		setTimeout(() => {
			if (!searchQuery.trim()) {
				isFocused = false;
			}
			showDropdown = false;
		}, 200);
	}
</script>

<div class="w-full px-4">
	<div class="relative">
		<!-- Search Input (styled like CompactChatInput) -->
		<div
			class="relative bg-white border rounded-2xl transition-all duration-300 {isFocused
				? 'border-teal-600/40 shadow-lg'
				: 'border-slate-300 shadow-sm hover:shadow-md hover:border-slate-400'}"
		>
			<input
				type="text"
				bind:value={searchQuery}
				oninput={handleInput}
				onfocus={handleFocus}
				onblur={handleBlur}
				placeholder="Search projects..."
				class="w-full px-5 py-3.5 bg-transparent outline-none text-slate-800 placeholder-slate-400 rounded-2xl pr-12"
				style="min-height: 52px;"
			/>

			<!-- Search Icon -->
			<div class="absolute right-3 top-1/2 -translate-y-1/2">
				<svg class="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
					></path>
				</svg>
			</div>
		</div>

		<!-- Dropdown Results -->
		{#if showDropdown && searchResults().length > 0}
			<div
				class="absolute z-50 w-full mt-2 bg-white rounded-xl shadow-2xl border border-slate-200 max-h-96 overflow-y-auto"
			>
				{#each searchResults() as result}
					<button
						onclick={() => selectProject(result.project_id)}
						class="w-full text-left px-5 py-3 hover:bg-teal-50 transition-colors border-b border-slate-100 last:border-b-0"
					>
						<div class="font-semibold text-slate-900">{result.project_name}</div>
						<div class="text-sm text-slate-600 mt-1">
							{result.area_name}
							{#if result.developer_name}
								• {result.developer_name}
							{/if}
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>
