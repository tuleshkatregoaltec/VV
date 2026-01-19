<script lang="ts">
	import { onMount } from 'svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import ProjectMap from '$lib/components/map/ProjectMap.svelte';
	import ProjectSearchInput from '$lib/components/projects/ProjectSearchInput.svelte';
	import ProjectDetails from '$lib/components/projects/ProjectDetails.svelte';
	import { projects as projectsAPI } from '$lib/api/projects';
	import type { ProjectDetailResponse, ProjectSearchResult } from '$lib/api/projects';

	let isMinimized = $state(false);
	let selectedProjectId = $state<number | null>(null);
	let projectDetails = $state<ProjectDetailResponse | null>(null);
	let isLoadingDetails = $state(false);
	let mapComponent = $state<any>();

	// Load all projects in background for client-side search
	let allProjects = $state<ProjectSearchResult[]>([]);

	onMount(async () => {
		// Load projects in background without blocking UI
		try {
			allProjects = await projectsAPI.list();
		} catch (error) {
			console.error('Failed to load projects:', error);
		}
	});

	async function handleProjectSelect(projectId: number) {
		selectedProjectId = projectId;
		isLoadingDetails = true;

		try {
			console.log('Fetching details for project:', projectId);
			projectDetails = await projectsAPI.getDetails(projectId);
			
			console.log('Project details received:', projectDetails);
			console.log('Area polygon:', projectDetails.area_polygon);
			console.log('Buildings:', projectDetails.buildings.length);

			// Fly map to project location with area polygon and building pins
			if (mapComponent && projectDetails) {
				console.log('Calling mapComponent.flyToProject');
				mapComponent.flyToProject(
					projectDetails.project_id,
					projectDetails.project_name,
					projectDetails.latitude,
					projectDetails.longitude,
					projectDetails.area_polygon,
					projectDetails.buildings,
					14
				);
			} else {
				console.error('Map component not ready or project details missing');
			}
		} catch (error) {
			console.error('Failed to load project details:', error);
		} finally {
			isLoadingDetails = false;
		}
	}

	function toggleMinimize() {
		isMinimized = !isMinimized;
	}
</script>

<AppShell showFilters={false}>
	<div class="relative h-[calc(100vh-64px)] overflow-hidden">
		<!-- Map (full screen) -->
		<div class="absolute inset-0">
			<ProjectMap bind:this={mapComponent} onProjectSelect={handleProjectSelect} />
		</div>

		<!-- Floating Left Overlay Panel -->
		<div
			class="absolute transition-all duration-300 ease-in-out z-10 {isMinimized
				? 'left-4 top-4'
				: 'left-4 right-4 top-4 bottom-4 sm:right-auto sm:w-96 bottom-4'}"
		>
			<div class="bg-white/95 backdrop-blur-md shadow-2xl rounded-2xl border border-slate-200/50 overflow-hidden {isMinimized ? '' : 'h-full'}">
				{#if isMinimized}
					<!-- Minimized State -->
					<div class="flex items-center gap-2 px-4 py-3">
						<span class="text-sm font-semibold text-slate-900 whitespace-nowrap">Projects</span>
						<button
							onclick={toggleMinimize}
							class="p-1.5 hover:bg-slate-100 transition-colors rounded-lg flex-shrink-0"
							aria-label="Expand panel"
						>
							<svg class="w-4 h-4 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"
								></path>
							</svg>
						</button>
					</div>
				{:else}
					<!-- Expanded State -->
					<div class="h-full flex flex-col">
						<!-- Header with Minimize Button -->
						<div class="flex items-center justify-between p-4 border-b border-slate-200 flex-shrink-0">
							<h1 class="text-xl font-bold text-slate-900">Projects</h1>
							<button
								onclick={toggleMinimize}
								class="p-2 hover:bg-slate-100 rounded-lg transition-colors"
								aria-label="Minimize panel"
							>
								<svg
									class="w-5 h-5 text-slate-600"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M15 19l-7-7 7-7"
									></path>
								</svg>
							</button>
						</div>

						<!-- Search Input - Always visible for perceived speed -->
						<div class="p-4 border-b border-slate-200 flex-shrink-0">
							<ProjectSearchInput allProjects={allProjects} onProjectSelect={handleProjectSelect} />
						</div>

						<!-- Content Area (scrollable) - Only scrollbar here -->
						<div class="flex-1 overflow-y-auto overflow-x-hidden">
							{#if isLoadingDetails}
								<div class="flex items-center justify-center h-full">
									<div class="text-slate-600">Loading project details...</div>
								</div>
							{:else if projectDetails}
								<ProjectDetails project={projectDetails} />
							{:else}
								<div class="flex flex-col items-center justify-center h-full px-6 text-center">
									<svg
										class="w-16 h-16 text-slate-300 mb-4"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
										></path>
									</svg>
									<h3 class="text-lg font-semibold text-slate-700 mb-2">Search for Projects</h3>
									<p class="text-sm text-slate-500">
										Use the search box above to find and explore Dubai real estate projects
									</p>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
	</div>
</AppShell>
