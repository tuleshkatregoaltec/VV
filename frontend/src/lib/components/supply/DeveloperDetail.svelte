<script lang="ts">
    import type { Developer, Project } from '$lib/api/supply';

    let {
        developer,
        projects = [],
        loading = false,
        selectedProjectId = $bindable<number | null>(null)
    }: {
        developer: Developer | null;
        projects?: Project[];
        loading?: boolean;
        selectedProjectId?: number | null;
    } = $props();

    function isPast(dateStr: string | null | undefined): boolean {
        if (!dateStr) return false;
        return new Date(dateStr) < new Date();
    }

    function getStatusColor(project: Project): string {
        if (isPast(project.cancellation_date)) return 'bg-red-100 text-red-700';
        if (isPast(project.completion_date)) return 'bg-green-100 text-green-700';
        const s = project.project_status?.toUpperCase() || '';
        if (s === 'FINISHED' || s === 'COMPLETED') return 'bg-green-100 text-green-700';
        if (s.includes('PROGRESS') || s.includes('CONSTRUCTION')) return 'bg-blue-100 text-blue-700';
        return 'bg-gray-100 text-gray-700';
    }

    function getStatusLabel(project: Project): string {
        if (isPast(project.cancellation_date)) return 'Cancelled';
        if (isPast(project.completion_date)) return 'Completed';
        return project.project_status || 'Unknown';
    }
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden h-full flex flex-col">
    {#if !developer}
        <div class="flex-1 flex items-center justify-center text-gray-500">
            <p>Select a developer to view details</p>
        </div>
    {:else if loading}
        <div class="flex-1 flex items-center justify-center">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
        </div>
    {:else}
        <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
            <h2 class="text-lg font-semibold text-gray-900">{developer.developer_name_en ?? 'Unknown'}</h2>
            {#if developer.phone}<p class="text-sm text-gray-500">{developer.phone}</p>{/if}
            {#if developer.webpage}
                <a href={developer.webpage} target="_blank" class="text-sm text-primary hover:underline">{developer.webpage}</a>
            {/if}
        </div>

        <div class="flex-1 overflow-y-auto">
            <!-- Stats - simplified info display -->
            <div class="px-6 py-3 border-b border-gray-100 flex gap-4 text-sm">
                <span class="text-gray-600"><strong>{developer.total}</strong> total</span>
                <span class="text-blue-600"><strong>{developer.active}</strong> active</span>
                <span class="text-green-600"><strong>{developer.completed}</strong> done</span>
                {#if developer.cancelled > 0}
                    <span class="text-red-600"><strong>{developer.cancelled}</strong> cancelled</span>
                {/if}
            </div>

            <!-- Projects -->
            <div class="px-6 py-4">
                <h3 class="text-sm font-medium text-gray-500 uppercase mb-3">Projects</h3>
                {#if projects.length === 0}
                    <p class="text-sm text-gray-500 italic text-center py-4">No projects</p>
                {:else}
                    <ul class="space-y-2">
                        {#each projects as project}
                            <li>
                                <button
                                    type="button"
                                    class="w-full text-left p-3 rounded-lg border transition-colors {selectedProjectId === project.project_id ? 'border-primary bg-primary/5' : 'border-gray-200 hover:bg-gray-50'}"
                                    onclick={() => selectedProjectId = project.project_id}
                                >
                                    <div class="flex items-center justify-between gap-2">
                                        <span class="font-medium text-gray-900 truncate">{project.project_name}</span>
                                        <span class="flex-shrink-0 px-2 py-0.5 text-xs rounded-full {getStatusColor(project)}">
                                            {getStatusLabel(project)}
                                        </span>
                                    </div>
                                    {#if project.area_name}
                                        <div class="text-xs text-gray-500 mt-1">{project.area_name}</div>
                                    {/if}
                                    {#if project.percent_completed != null && !project.cancellation_date}
                                        <div class="mt-2 w-full bg-gray-200 rounded-full h-1.5">
                                            <div class="bg-primary h-1.5 rounded-full" style="width: {project.percent_completed}%"></div>
                                        </div>
                                    {/if}
                                </button>
                            </li>
                        {/each}
                    </ul>
                {/if}
            </div>
        </div>
    {/if}
</div>
