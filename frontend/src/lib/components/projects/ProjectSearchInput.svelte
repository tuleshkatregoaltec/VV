<script lang="ts">
	import type { ProjectSearchResult, SearchSelection } from '$lib/api/projects';

	let {
		allProjects,
		onSelect
	}: {
		allProjects: ProjectSearchResult[];
		onSelect: (sel: SearchSelection) => void;
	} = $props();

	let searchQuery = $state('');
	let isFocused = $state(false);
	let showDropdown = $state(false);

	// Build master index: masterName → { count, areaName }
	let masterIndex = $derived.by(() => {
		const map = new Map<string, { count: number; areaName: string }>();
		for (const p of allProjects) {
			if (p.master_project_en) {
				const existing = map.get(p.master_project_en);
				if (existing) {
					existing.count++;
				} else {
					map.set(p.master_project_en, { count: 1, areaName: p.area_name });
				}
			}
		}
		return map;
	});

	let searchResults = $derived.by(() => {
		const q = searchQuery.trim().toLowerCase();
		if (q.length < 2) return { masters: [], projects: [] };

		const masters: Array<{ name: string; count: number; areaName: string }> = [];
		for (const [name, info] of masterIndex) {
			if (name.toLowerCase().includes(q)) {
				masters.push({ name, count: info.count, areaName: info.areaName });
			}
		}

		const projects = allProjects
			.filter(
				(p) =>
					p.project_name.toLowerCase().includes(q) ||
					p.area_name.toLowerCase().includes(q) ||
					(p.developer_name && p.developer_name.toLowerCase().includes(q))
			)
			.slice(0, 20);

		return { masters: masters.slice(0, 5), projects };
	});

	const hasResults = $derived(
		searchResults.masters.length > 0 || searchResults.projects.length > 0
	);

	function handleInput() {
		showDropdown = searchQuery.trim().length >= 2;
	}

	function selectMaster(masterName: string) {
		onSelect({ type: 'master', masterName });
		searchQuery = masterName;
		showDropdown = false;
		isFocused = false;
	}

	function selectProject(projectId: number) {
		onSelect({ type: 'project', projectId });
		searchQuery = '';
		showDropdown = false;
		isFocused = false;
	}

	function handleFocus() {
		isFocused = true;
		if (searchQuery.trim().length >= 2) showDropdown = true;
	}

	function handleBlur() {
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

		{#if showDropdown && hasResults}
			<div
				onmousedown={(e) => e.preventDefault()}
				class="absolute z-50 w-full mt-1 bg-white rounded-xl shadow-2xl border border-slate-200 max-h-80 overflow-y-auto"
			>
				<!-- Master projects first -->
				{#each searchResults.masters as master}
					<button
						onclick={() => selectMaster(master.name)}
						class="w-full text-left px-4 py-2.5 hover:bg-teal-50 transition-colors border-b border-slate-100"
					>
						<div class="flex items-start justify-between gap-2">
							<div class="min-w-0">
								<div class="text-sm font-semibold text-slate-900 truncate">{master.name}</div>
								<div class="text-xs text-slate-500 mt-0.5">{master.areaName}</div>
							</div>
							<div class="flex flex-col items-end gap-1 flex-shrink-0">
								<span class="text-[10px] font-medium px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700">
									Master
								</span>
								<span class="text-[10px] text-slate-400">{master.count} projects</span>
							</div>
						</div>
					</button>
				{/each}

				<!-- Individual projects -->
				{#each searchResults.projects as result}
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
