<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { supply, type UpcomingProject } from '$lib/api/supply';

	let searchQuery = $state('');
	let timeframeFilter = $state<'all' | 'upcoming' | '3m' | '6m' | '12m' | 'overdue'>('all');
	let sortBy = $state<{ column: string; direction: 'asc' | 'desc' }>({
		column: 'project_end_date',
		direction: 'asc'
	});
	let selectedProject: UpcomingProject | null = $state(null);

	// Query for projects using TanStack Query
	const projectsQuery = createQuery(() => ({
		queryKey: ['supply-projects'],
		queryFn: () => supply.getUpcomingProjects()
	}));

	// Computed filtered projects
	let filteredProjects = $derived.by(() => {
		const data = projectsQuery.data;
		if (!data) return [];

		let result = [...data.projects];

		// 1. Search filter (project name OR developer name)
		if (searchQuery.trim()) {
			const q = searchQuery.toLowerCase();
			result = result.filter(
				(p) =>
					p.project_name.toLowerCase().includes(q) ||
					p.developer_name.toLowerCase().includes(q)
			);
		}

		// 2. Timeframe filter
		const now = new Date();
		if (timeframeFilter === 'all') {
			// Show all active projects - no date filtering
			// result stays as-is
		} else if (timeframeFilter === 'upcoming') {
			// Only show projects with future completion dates
			result = result.filter((p) => !p.project_end_date || new Date(p.project_end_date) >= now);
		} else if (timeframeFilter === 'overdue') {
			// Show only past-due projects
			result = result.filter((p) => p.project_end_date && new Date(p.project_end_date) < now);
		} else {
			// Next 3/6/12 months
			const months = timeframeFilter === '3m' ? 3 : timeframeFilter === '6m' ? 6 : 12;
			const futureDate = new Date(now);
			futureDate.setMonth(futureDate.getMonth() + months);

			result = result.filter(
				(p) =>
					p.project_end_date &&
					new Date(p.project_end_date) >= now &&
					new Date(p.project_end_date) <= futureDate
			);
		}

		// 3. Sort
		result.sort((a, b) => {
			const aVal = a[sortBy.column as keyof UpcomingProject];
			const bVal = b[sortBy.column as keyof UpcomingProject];
			if (aVal === null || aVal === undefined) return 1;
			if (bVal === null || bVal === undefined) return -1;
			const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
			return sortBy.direction === 'asc' ? cmp : -cmp;
		});

		return result;
	});

	function formatDate(dateStr: string | null): string {
		if (!dateStr) return 'TBD';
		const date = new Date(dateStr);
		return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
	}

	function toggleSort(column: string) {
		if (sortBy.column === column) {
			sortBy = { ...sortBy, direction: sortBy.direction === 'asc' ? 'desc' : 'asc' };
		} else {
			sortBy = { column, direction: 'asc' };
		}
	}
</script>

<div class="h-full flex flex-col bg-slate-50">
	<!-- Header -->
	<div class="px-6 py-4 bg-white/80 backdrop-blur-sm border-b border-slate-200">
		<h1 class="text-2xl font-bold text-slate-900">Active Projects</h1>
		<p class="text-sm text-slate-500">Track active development projects across Dubai</p>
	</div>

	<!-- Filters -->
	<div class="px-6 py-4 bg-white/80 backdrop-blur-sm border-b border-slate-200">
		<div class="flex gap-4 items-center">
			<input
				type="text"
				placeholder="Search projects or developers..."
				bind:value={searchQuery}
				class="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary"
			/>
			<select
				bind:value={timeframeFilter}
				class="px-4 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary focus:border-primary"
			>
				<option value="all">All Active</option>
				<option value="upcoming">Upcoming Only</option>
				<option value="3m">Next 3 Months</option>
				<option value="6m">Next 6 Months</option>
				<option value="12m">Next 12 Months</option>
				<option value="overdue">Overdue</option>
			</select>
			<span class="text-sm text-slate-600 whitespace-nowrap"
				>{filteredProjects.length} project{filteredProjects.length !== 1 ? 's' : ''}</span
			>
		</div>
	</div>

	<!-- Table -->
	<div class="flex-1 overflow-auto">
		{#if projectsQuery.isLoading}
			<div class="flex items-center justify-center h-full">
				<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
			</div>
		{:else if projectsQuery.error}
			<div class="flex items-center justify-center h-full">
				<div class="text-center">
					<p class="text-red-600 font-semibold">Error loading projects</p>
					<p class="text-slate-500 text-sm mt-2">{projectsQuery.error.message}</p>
				</div>
			</div>
		{:else}
			<table class="w-full">
				<thead class="bg-slate-100 sticky top-0 z-10">
					<tr class="text-left text-xs font-medium text-slate-700 uppercase tracking-wider">
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('project_name')}
						>
							Project Name
							{#if sortBy.column === 'project_name'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('developer_name')}
						>
							Developer
							{#if sortBy.column === 'developer_name'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('area_name')}
						>
							Area
							{#if sortBy.column === 'area_name'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('percent_completed')}
						>
							Progress
							{#if sortBy.column === 'percent_completed'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('project_start_date')}
						>
							Started
							{#if sortBy.column === 'project_start_date'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
						<th
							class="px-6 py-3 cursor-pointer hover:bg-slate-200 transition-colors"
							onclick={() => toggleSort('project_end_date')}
						>
							Expected Completion
							{#if sortBy.column === 'project_end_date'}
								<span class="ml-1">{sortBy.direction === 'asc' ? '↑' : '↓'}</span>
							{/if}
						</th>
					</tr>
				</thead>
				<tbody class="bg-white divide-y divide-slate-200">
					{#each filteredProjects as project (project.project_id)}
						<tr
							class="hover:bg-slate-50 cursor-pointer transition-colors"
							onclick={() => (selectedProject = project)}
						>
							<td class="px-6 py-4 font-medium text-slate-900">{project.project_name}</td>
							<td class="px-6 py-4 text-slate-600">{project.developer_name}</td>
							<td class="px-6 py-4 text-slate-600">{project.area_name}</td>
							<td class="px-6 py-4">
								<div class="flex items-center gap-2">
									<div class="flex-1 h-2 bg-slate-200 rounded-full overflow-hidden max-w-24">
										<div
											class="h-full bg-primary transition-all"
											style="width: {project.percent_completed}%"
										></div>
									</div>
									<span class="text-sm text-slate-600 w-12 text-right"
										>{project.percent_completed}%</span
									>
								</div>
							</td>
							<td class="px-6 py-4 text-slate-600">{formatDate(project.project_start_date)}</td>
							<td class="px-6 py-4 font-medium text-slate-900">
								{formatDate(project.project_end_date)}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>

			{#if filteredProjects.length === 0}
				<div class="text-center py-12 text-slate-500">
					{searchQuery ? 'No projects found matching your search' : 'No active projects'}
				</div>
			{/if}
		{/if}
	</div>
</div>

<!-- Project Detail Modal (if selected) -->
{#if selectedProject}
	<div
		class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4"
		role="button"
		tabindex="0"
		onclick={() => (selectedProject = null)}
		onkeydown={(e) => e.key === 'Escape' && (selectedProject = null)}
	>
		<div
			class="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto"
			role="dialog"
			aria-modal="true"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
		>
			<div class="sticky top-0 bg-white border-b border-gray-200 px-6 py-4">
				<div class="flex justify-between items-start">
					<div>
						<h2 class="text-xl font-bold text-gray-900">{selectedProject.project_name}</h2>
					</div>
					<button
						onclick={() => (selectedProject = null)}
						class="text-gray-400 hover:text-gray-600 transition-colors"
						aria-label="Close modal"
					>
						<svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							></path>
						</svg>
					</button>
				</div>
			</div>

			<div class="p-6 space-y-6">
				<!-- Progress -->
				<div>
					<h3 class="text-sm font-semibold text-gray-700 mb-2">Progress</h3>
					<div class="flex items-center gap-4">
						<div class="flex-1 h-4 bg-gray-200 rounded-full overflow-hidden">
							<div
								class="h-full bg-primary transition-all"
								style="width: {selectedProject.percent_completed}%"
							></div>
						</div>
						<span class="text-lg font-semibold text-gray-900"
							>{selectedProject.percent_completed}%</span
						>
					</div>
				</div>

				<!-- Details Grid -->
				<div class="grid grid-cols-2 gap-4">
					<div>
						<h3 class="text-sm font-semibold text-gray-700 mb-1">Developer</h3>
						<p class="text-gray-900">{selectedProject.developer_name}</p>
					</div>
					<div>
						<h3 class="text-sm font-semibold text-gray-700 mb-1">Area</h3>
						<p class="text-gray-900">{selectedProject.area_name}</p>
					</div>
					<div>
						<h3 class="text-sm font-semibold text-gray-700 mb-1">Started</h3>
						<p class="text-gray-900">{formatDate(selectedProject.project_start_date)}</p>
					</div>
					<div>
						<h3 class="text-sm font-semibold text-gray-700 mb-1">Expected Completion</h3>
						<p class="text-gray-900">{formatDate(selectedProject.project_end_date)}</p>
					</div>
					{#if selectedProject.no_of_buildings}
						<div>
							<h3 class="text-sm font-semibold text-gray-700 mb-1">Buildings</h3>
							<p class="text-gray-900">{selectedProject.no_of_buildings}</p>
						</div>
					{/if}
					{#if selectedProject.no_of_units}
						<div>
							<h3 class="text-sm font-semibold text-gray-700 mb-1">Units</h3>
							<p class="text-gray-900">{selectedProject.no_of_units}</p>
						</div>
					{/if}
				</div>
			</div>

			<div class="sticky bottom-0 bg-gray-50 px-6 py-4 border-t border-gray-200">
				<button
					onclick={() => (selectedProject = null)}
					class="w-full px-4 py-2 bg-gray-200 text-gray-700 rounded-lg hover:bg-gray-300 transition-colors font-medium"
				>
					Close
				</button>
			</div>
		</div>
	</div>
{/if}
