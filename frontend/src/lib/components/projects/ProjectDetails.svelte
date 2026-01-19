<script lang="ts">
	import type { ProjectDetailResponse } from '$lib/api/projects';

	let {
		project
	}: {
		project: ProjectDetailResponse;
	} = $props();
</script>

<div class="p-6 space-y-6">
	<!-- Header -->
	<div class="border-b border-slate-200 pb-4">
		<h2 class="text-2xl font-bold text-slate-900">{project.project_name}</h2>
		<div class="flex items-center gap-2 mt-2 text-sm text-slate-600">
			<span>{project.area_name}</span>
			{#if project.developer_name}
				<span>•</span>
				<span>{project.developer_name}</span>
			{/if}
		</div>
	</div>

	<!-- Metrics Grid -->
	<div class="grid grid-cols-2 gap-4">
		{#if project.no_of_buildings}
			<div class="bg-slate-50 rounded-lg p-4">
				<div class="text-sm text-slate-600">Buildings</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_buildings}</div>
			</div>
		{/if}

		{#if project.no_of_units}
			<div class="bg-slate-50 rounded-lg p-4">
				<div class="text-sm text-slate-600">Units</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_units}</div>
			</div>
		{/if}

		{#if project.no_of_villas}
			<div class="bg-slate-50 rounded-lg p-4">
				<div class="text-sm text-slate-600">Villas</div>
				<div class="text-2xl font-bold text-slate-900">{project.no_of_villas}</div>
			</div>
		{/if}

		{#if project.percent_completed !== null}
			<div class="bg-slate-50 rounded-lg p-4">
				<div class="text-sm text-slate-600">Completed</div>
				<div class="text-2xl font-bold text-teal-600">{project.percent_completed}%</div>
			</div>
		{/if}
	</div>

	<!-- Timeline -->
	{#if project.project_start_date || project.project_end_date}
		<div class="space-y-2">
			<h3 class="font-semibold text-slate-900">Timeline</h3>
			<div class="space-y-1 text-sm">
				{#if project.project_start_date}
					<div class="flex justify-between">
						<span class="text-slate-600">Started:</span>
						<span class="font-medium"
							>{new Date(project.project_start_date).toLocaleDateString()}</span
						>
					</div>
				{/if}
				{#if project.project_end_date}
					<div class="flex justify-between">
						<span class="text-slate-600">Expected Completion:</span>
						<span class="font-medium"
							>{new Date(project.project_end_date).toLocaleDateString()}</span
						>
					</div>
				{/if}
				{#if project.completion_date}
					<div class="flex justify-between">
						<span class="text-slate-600">Completed:</span>
						<span class="font-medium"
							>{new Date(project.completion_date).toLocaleDateString()}</span
						>
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Unit Composition -->
	{#if project.unit_composition.length > 0}
		<div class="space-y-3">
			<h3 class="font-semibold text-slate-900">Unit Composition</h3>
			<div class="space-y-2">
				{#each project.unit_composition as unit_type}
					<div class="flex items-center justify-between">
						<div class="flex-1">
							<div class="flex items-center justify-between mb-1">
								<span class="text-sm font-medium text-slate-700">{unit_type.property_sub_type}</span
								>
								<span class="text-sm text-slate-600"
									>{unit_type.count} units ({unit_type.percentage}%)</span
								>
							</div>
							<div class="w-full bg-slate-200 rounded-full h-2">
								<div
									class="bg-gradient-to-r from-teal-600 to-cyan-600 h-2 rounded-full transition-all"
									style="width: {unit_type.percentage}%"
								></div>
							</div>
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Master Developer -->
	{#if project.master_developer_name && project.master_developer_name !== project.developer_name}
		<div class="text-sm">
			<span class="text-slate-600">Master Developer:</span>
			<span class="font-medium text-slate-900">{project.master_developer_name}</span>
		</div>
	{/if}
</div>
