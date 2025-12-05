<script lang="ts">
    import DeveloperList from '$lib/components/supply/DeveloperList.svelte';
    import DeveloperDetail from '$lib/components/supply/DeveloperDetail.svelte';
    import ProjectDetail from '$lib/components/supply/ProjectDetail.svelte';
    import { supply, type Developer, type Project, type SortOption } from '$lib/api/supply';

    let selectedDeveloperId: number | null = $state(null);
    let selectedDeveloper: Developer | null = $state(null);
    let projects: Project[] = $state([]);
    let selectedProjectId: number | null = $state(null);
    let selectedProject: Project | null = $state(null);

    let loadingProjects = $state(false);
    let loadingProject = $state(false);
    
    let sortBy: SortOption = $state('projects');
    let statusFilter: 'all' | 'active' | 'completed' | 'cancelled' = $state('all');

    $effect(() => {
        if (selectedDeveloperId) {
            loadingProjects = true;
            selectedProjectId = null;
            selectedProject = null;
            supply.getDeveloperProjects(selectedDeveloperId)
                .then(p => projects = p)
                .catch(e => console.error(e))
                .finally(() => loadingProjects = false);
        } else {
            projects = [];
        }
    });

    $effect(() => {
        if (selectedProjectId) {
            loadingProject = true;
            supply.getProject(selectedProjectId)
                .then(p => selectedProject = p)
                .catch(e => console.error(e))
                .finally(() => loadingProject = false);
        } else {
            selectedProject = null;
        }
    });
</script>


<div class="h-full flex flex-col">
    <div class="px-6 py-4 border-b border-gray-200 bg-white">
        <h1 class="text-2xl font-bold text-gray-900">Supply</h1>
        <p class="text-sm text-gray-500">Browse developers and their projects</p>
    </div>

    <div class="flex-1 p-6 overflow-hidden">
        <div class="h-full grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div class="h-full min-h-0 overflow-hidden">
                <DeveloperList bind:selectedId={selectedDeveloperId} bind:selectedDeveloper bind:sortBy bind:statusFilter />
            </div>
            <div class="h-full min-h-0 overflow-hidden">
                <DeveloperDetail developer={selectedDeveloper} {projects} loading={loadingProjects} bind:selectedProjectId />
            </div>
            <div class="h-full min-h-0 overflow-hidden">
                <ProjectDetail project={selectedProject} loading={loadingProject} />
            </div>
        </div>
    </div>
</div>

