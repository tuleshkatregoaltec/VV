<script lang="ts">
	import type { ProjectDetailResponse } from '$lib/api/projects';

	let {
		project,
		analytics = null,
		onBuildingSelect
	}: {
		project: ProjectDetailResponse;
		analytics?: { avg_price: number; gross_yield_pct: number | null } | null;
		onBuildingSelect?: (propertyId: number, lng: number, lat: number) => void;
	} = $props();

	function formatCurrency(value: number): string {
		if (value >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(1)}M`;
		if (value >= 1_000) return `AED ${Math.round(value / 1_000)}K`;
		return `AED ${value.toLocaleString()}`;
	}

	function formatDate(d: string | null): string | null {
		if (!d) return null;
		return new Date(d).toLocaleDateString('en-GB', { month: 'short', year: 'numeric' });
	}

	const isCompleted = $derived(project.project_status === 'C');
	const location = $derived(project.master_project_en || project.area_name);
</script>

<div class="p-5 space-y-5">
	<!-- Header -->
	<div class="border-b border-slate-200 pb-4">
		<h2 class="text-xl font-bold text-slate-900 leading-tight">{project.project_name}</h2>
		<div class="flex flex-wrap items-center gap-x-2 gap-y-1 mt-2 text-sm text-slate-500">
			<span class="flex items-center gap-1">
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z"></path>
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"></path>
				</svg>
				{location}
			</span>
			{#if project.developer_name}
				<span class="text-slate-300">•</span>
				<span>{project.developer_name}</span>
			{/if}
		</div>
	</div>

	<!-- Project Metrics -->
	<div class="grid grid-cols-2 gap-3">
		{#if project.no_of_buildings}
			<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
				<div class="text-xs text-slate-500 mb-1">Buildings</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_buildings}</div>
			</div>
		{/if}
		{#if project.no_of_units}
			<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
				<div class="text-xs text-slate-500 mb-1">Units</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_units.toLocaleString()}</div>
			</div>
		{/if}
		{#if project.no_of_villas}
			<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
				<div class="text-xs text-slate-500 mb-1">Villas</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_villas}</div>
			</div>
		{/if}
		{#if project.no_of_lands}
			<div class="bg-slate-50 rounded-xl p-3 border border-slate-100">
				<div class="text-xs text-slate-500 mb-1">Plots</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_lands}</div>
			</div>
		{/if}
	</div>

	<!-- Analytics KPIs -->
	{#if analytics}
		<div class="grid grid-cols-2 gap-3">
			{#if analytics.avg_price}
				<div class="bg-teal-50 rounded-xl p-3 border border-teal-100">
					<div class="text-xs text-teal-600 mb-1">Avg Sale Price</div>
					<div class="text-xl font-bold text-teal-800">{formatCurrency(analytics.avg_price)}</div>
				</div>
			{/if}
			{#if analytics.gross_yield_pct != null}
				<div class="bg-teal-50 rounded-xl p-3 border border-teal-100">
					<div class="text-xs text-teal-600 mb-1">Gross Yield</div>
					<div class="text-xl font-bold text-teal-800">{analytics.gross_yield_pct.toFixed(1)}%</div>
				</div>
			{/if}
		</div>
	{/if}

	<!-- Unit Composition -->
	{#if project.unit_composition.length > 0}
		<div class="space-y-2.5">
			<h3 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">Unit Mix</h3>
			<div class="space-y-2">
				{#each project.unit_composition as unit_type}
					<div>
						<div class="flex items-center justify-between mb-1">
							<span class="text-sm font-medium text-slate-700">{unit_type.property_sub_type}</span>
							<span class="text-xs text-slate-500">{unit_type.count.toLocaleString()} · {unit_type.percentage}%</span>
						</div>
						<div class="w-full bg-slate-200 rounded-full h-1.5">
							<div
								class="bg-gradient-to-r from-teal-500 to-cyan-500 h-1.5 rounded-full"
								style="width: {unit_type.percentage}%"
							></div>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Buildings List -->
	{#if project.buildings && project.buildings.length > 0}
		<div class="space-y-2">
			<h3 class="text-sm font-semibold text-slate-700 uppercase tracking-wide">
				Buildings ({project.buildings.length})
			</h3>
			<div class="space-y-1.5 max-h-48 overflow-y-auto">
				{#each project.buildings as building, i}
					<button
						onclick={() => onBuildingSelect?.(building.property_id, building.longitude, building.latitude)}
						class="w-full flex items-center gap-3 bg-slate-50 rounded-lg px-3 py-2 border border-slate-100 hover:bg-teal-50 hover:border-teal-200 transition-colors text-left"
					>
						<span class="w-5 h-5 bg-amber-500 rounded flex items-center justify-center text-[10px] font-bold text-white flex-shrink-0">
							{i + 1}
						</span>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium text-slate-900 truncate">
								{building.building_name || building.building_number || `Building ${i + 1}`}
							</div>
							{#if building.floors}
								<div class="text-xs text-slate-500">{building.floors} floors</div>
							{/if}
						</div>
						<svg class="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
						</svg>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Timeline / Progress -->
	{#if project.project_start_date || project.project_end_date || project.completion_date || project.percent_completed != null}
		<div class="border-t border-slate-100 pt-4 space-y-2 text-sm">
			{#if isCompleted}
				<!-- Completed: just show start and finish -->
				{#if project.project_start_date}
					<div class="flex justify-between">
						<span class="text-slate-500">Started</span>
						<span class="font-medium text-slate-700">{formatDate(project.project_start_date)}</span>
					</div>
				{/if}
				<div class="flex justify-between">
					<span class="text-slate-500">Completed</span>
					<span class="font-medium text-emerald-600">{formatDate(project.completion_date || project.project_end_date)}</span>
				</div>
			{:else}
				<!-- In progress: show start, expected, and progress bar -->
				{#if project.project_start_date}
					<div class="flex justify-between">
						<span class="text-slate-500">Started</span>
						<span class="font-medium text-slate-700">{formatDate(project.project_start_date)}</span>
					</div>
				{/if}
				{#if project.project_end_date}
					<div class="flex justify-between">
						<span class="text-slate-500">Expected</span>
						<span class="font-medium text-slate-700">{formatDate(project.project_end_date)}</span>
					</div>
				{/if}
				{#if project.percent_completed != null}
					<div class="pt-1">
						<div class="flex justify-between text-xs mb-1.5">
							<span class="text-slate-500">Progress</span>
							<span class="font-semibold text-teal-700">{project.percent_completed}%</span>
						</div>
						<div class="w-full bg-slate-200 rounded-full h-1.5">
							<div
								class="bg-gradient-to-r from-teal-500 to-cyan-500 h-1.5 rounded-full"
								style="width: {project.percent_completed}%"
							></div>
						</div>
					</div>
				{/if}
			{/if}
		</div>
	{/if}

	<!-- Master Developer (only if different from main developer) -->
	{#if project.master_developer_name && project.master_developer_name !== project.developer_name}
		<div class="text-xs text-slate-500 border-t border-slate-100 pt-3">
			Master Developer: <span class="font-medium text-slate-700">{project.master_developer_name}</span>
		</div>
	{/if}
</div>
