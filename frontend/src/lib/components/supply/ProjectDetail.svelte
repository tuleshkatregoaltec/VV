<script lang="ts">
    import type { Project } from '$lib/api/supply';

    let { project, loading = false }: { project: Project | null; loading?: boolean } = $props();

    const fmt = (d?: string) => d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }) : '-';
    const isPast = (d?: string) => d ? new Date(d) < new Date() : false;
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden h-full flex flex-col">
    {#if !project}
        <div class="flex-1 flex items-center justify-center text-gray-500">
            <p>Select a project to view details</p>
        </div>
    {:else if loading}
        <div class="flex-1 flex items-center justify-center">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
    {:else}
        <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
            <h2 class="text-lg font-semibold text-gray-900">{project.project_name}</h2>
            {#if project.area_name}<p class="text-sm text-gray-500">{project.area_name}</p>{/if}
            {#if project.percent_completed != null && !isPast(project.cancellation_date)}
                <div class="mt-2 w-full bg-gray-200 rounded-full h-2">
                    <div class="bg-primary h-2 rounded-full" style="width: {project.percent_completed}%"></div>
                </div>
                <p class="text-xs text-gray-500 mt-1">{project.percent_completed}% complete</p>
            {/if}
        </div>

        <div class="flex-1 overflow-y-auto p-6 space-y-4">
            {#if isPast(project.cancellation_date)}
                <div class="px-4 py-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
                    <strong>Cancelled:</strong> {fmt(project.cancellation_date)}
                </div>
            {:else if isPast(project.completion_date)}
                <div class="px-4 py-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
                    <strong>Completed:</strong> {fmt(project.completion_date)}
                </div>
            {/if}

            <div>
                <h3 class="text-xs font-medium text-gray-500 uppercase mb-2">Timeline</h3>
                <div class="grid grid-cols-2 gap-2 text-sm">
                    <div><span class="text-gray-500">Start:</span> {fmt(project.project_start_date)}</div>
                    <div><span class="text-gray-500">Target End:</span> {fmt(project.project_end_date)}</div>
                    {#if project.completion_date}
                        <div class="col-span-2"><span class="text-gray-500">Actual Completion:</span> {fmt(project.completion_date)}</div>
                    {/if}
                </div>
            </div>

            <div>
                <h3 class="text-xs font-medium text-gray-500 uppercase mb-2">Property Counts</h3>
                <div class="grid grid-cols-2 gap-2 text-sm">
                    <div><span class="text-gray-500">Buildings:</span> {project.no_of_buildings ?? '-'}</div>
                    <div><span class="text-gray-500">Units:</span> {project.no_of_units ?? '-'}</div>
                </div>
            </div>

            {#if project.project_description}
                <div>
                    <h3 class="text-xs font-medium text-gray-500 uppercase mb-2">Description</h3>
                    <p class="text-sm text-gray-700">{project.project_description}</p>
                </div>
            {/if}
        </div>
    {/if}
</div>
