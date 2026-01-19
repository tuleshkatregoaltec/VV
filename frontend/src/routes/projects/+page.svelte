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

	// Load all projects on mount for client-side search
	let allProjects = $state<ProjectSearchResult[]>([]);
	let isLoadingProjects = $state(true);

	onMount(async () => {
		try {
			allProjects = await projectsAPI.list();
		} catch (error) {
			console.error('Failed to load projects:', error);
		} finally {
			isLoadingProjects = false;
		}
	});

	async function handleProjectSelect(projectId: number) {
		selectedProjectId = projectId;
		isLoadingDetails = true;

		try {
			projectDetails = await projectsAPI.getDetails(projectId);
			// TODO: Fly map to project location when we have coordinates
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
	<div class="relative h-[calc(100vh-64px)]">
		<!-- Map (full screen) -->
		<div class="absolute inset-0">
			<ProjectMap bind:this={mapComponent} onProjectSelect={handleProjectSelect} />
		</div>

		<!-- Left Overlay Panel -->
		<div
			class="absolute left-0 top-0 bottom-0 transition-all duration-300 ease-in-out z-10 {isMinimized
				? 'w-16'
				: 'w-full sm:w-96'}"
		>
			<div class="h-full bg-white/90 backdrop-blur-md shadow-2xl border-r border-slate-200">
				{#if isMinimized}
					<!-- Minimized State -->
					<button
						onclick={toggleMinimize}
						class="w-full h-16 flex items-center justify-center hover:bg-slate-100 transition-colors"
						aria-label="Expand panel"
					>
						<svg class="w-6 h-6 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"
							></path>
						</svg>
					</button>
				{:else}
					<!-- Expanded State -->
					<div class="h-full flex flex-col">
						<!-- Header with Minimize Button -->
						<div class="flex items-center justify-between p-4 border-b border-slate-200">
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

						<!-- Search Input -->
						<div class="p-4 border-b border-slate-200">
							{#if isLoadingProjects}
								<div class="text-center text-slate-500 py-4">Loading projects...</div>
							{:else}
								<ProjectSearchInput allProjects={allProjects} onProjectSelect={handleProjectSelect} />
							{/if}
						</div>

						<!-- Content Area (scrollable) -->
						<div class="flex-1 overflow-y-auto">
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
