<script lang="ts">
	import { onMount } from 'svelte';
	import AppShell from '$lib/components/layout/AppShell.svelte';
	import ProjectMap from '$lib/components/map/ProjectMap.svelte';
	import ProjectSearchInput from '$lib/components/projects/ProjectSearchInput.svelte';
	import ProjectDetails from '$lib/components/projects/ProjectDetails.svelte';
	import MasterProjectPanel from '$lib/components/projects/MasterProjectPanel.svelte';
	import BuildingDetails from '$lib/components/projects/BuildingDetails.svelte';
	import { projects as projectsAPI } from '$lib/api/projects';
	import type {
		ProjectDetailResponse,
		MasterProjectResponse,
		BuildingDetailResponse,
		ProjectSearchResult,
		SearchSelection,
		GeoPin
	} from '$lib/api/projects';

	let isMinimized = $state(false);
	let projectDetails = $state<ProjectDetailResponse | null>(null);
	let masterDetails = $state<MasterProjectResponse | null>(null);
	let buildingDetails = $state<BuildingDetailResponse | null>(null);
	let projectAnalytics = $state<{ avg_price: number; gross_yield_pct: number | null } | null>(null);
	let isLoading = $state(false);
	let panelView = $state<'empty' | 'project' | 'building' | 'master'>('empty');
	let mapComponent = $state<any>();

	let allProjects = $state<ProjectSearchResult[]>([]);

	onMount(async () => {
		try {
			allProjects = await projectsAPI.list();
		} catch (error) {
			console.error('Failed to load projects:', error);
		}
	});

	// Hardcoded JVC (Jumeirah Village Circle) boundary polygon [lng, lat]
	const JVC_POLYGON: Array<[number, number]> = [
		[55.1880, 25.0740],
		[55.2020, 25.0790],
		[55.2180, 25.0785],
		[55.2320, 25.0700],
		[55.2390, 25.0570],
		[55.2360, 25.0430],
		[55.2240, 25.0340],
		[55.2060, 25.0300],
		[55.1900, 25.0340],
		[55.1770, 25.0440],
		[55.1740, 25.0580],
		[55.1810, 25.0700],
		[55.1880, 25.0740]
	];

	const JVC_ANALYTICS = { avg_price: 975000, gross_yield_pct: 7.2 };

	function isJVCProject(areaName: string, projectName: string): boolean {
		const a = areaName.toLowerCase();
		const p = projectName.toLowerCase();
		return (
			a.includes('al barsha south fourth') ||
			a.includes('jumeirah village circle') ||
			p.includes('jumeirah village circle')
		);
	}

	async function handleSearchSelect(sel: SearchSelection) {
		if (sel.type === 'master') {
			await handleMasterSelect(sel.masterName);
		} else {
			await handleProjectSelect(sel.projectId);
		}
	}

	async function handleMasterSelect(masterName: string) {
		isLoading = true;
		projectDetails = null;
		buildingDetails = null;
		projectAnalytics = null;
		panelView = 'master';

		try {
			masterDetails = await projectsAPI.getMaster(masterName);
			if (masterDetails && mapComponent && masterDetails.geo_pins.length > 0) {
				mapComponent.fitBounds(masterDetails.geo_pins);
			}
		} catch (error) {
			console.error('Failed to load master project:', error);
			panelView = 'empty';
		} finally {
			isLoading = false;
		}
	}

	async function handleProjectSelect(projectId: number) {
		isLoading = true;
		buildingDetails = null;
		projectAnalytics = null;
		panelView = 'project';

		try {
			const details = await projectsAPI.getDetails(projectId);

			if (isJVCProject(details.area_name, details.project_name)) {
				details.latitude = 25.0565;
				details.longitude = 55.2065;
				details.area_polygon = { coordinates: JVC_POLYGON };
				projectAnalytics = JVC_ANALYTICS;
			}

			projectDetails = details;

			if (mapComponent) {
				mapComponent.flyToProject(
					details.project_id,
					details.project_name,
					details.latitude,
					details.longitude,
					details.area_polygon,
					details.geo_pins,
					13
				);
			}
		} catch (error) {
			console.error('Failed to load project details:', error);
			panelView = 'empty';
		} finally {
			isLoading = false;
		}
	}

	async function handleBuildingSelect(propertyId: number, lng?: number, lat?: number) {
		isLoading = true;
		panelView = 'building';

		if (lng && lat && mapComponent) {
			mapComponent.flyToLocation(lng, lat, 17);
		}

		try {
			buildingDetails = await projectsAPI.getBuilding(propertyId);
		} catch (error) {
			console.error('Failed to load building details:', error);
			panelView = 'project';
		} finally {
			isLoading = false;
		}
	}

	function handleBuildingPinClick(pin: GeoPin) {
		if (pin.property_id) {
			handleBuildingSelect(pin.property_id, pin.longitude, pin.latitude);
		} else {
			mapComponent?.flyToLocation(pin.longitude, pin.latitude, 17);
		}
	}

	function handleGeoPinSelect(lat: number, lng: number) {
		if (mapComponent) mapComponent.flyToLocation(lng, lat, 17);
	}

	function handleBackToProject() {
		buildingDetails = null;
		panelView = 'project';
	}

	function toggleMinimize() {
		isMinimized = !isMinimized;
	}
</script>

<AppShell showFilters={false}>
	<div class="relative h-[calc(100vh-64px)] overflow-hidden">
		<!-- Map (full screen) -->
		<div class="absolute inset-0">
			<ProjectMap
				bind:this={mapComponent}
				onProjectSelect={handleProjectSelect}
				onBuildingPinClick={handleBuildingPinClick}
			/>
		</div>

		<!-- Floating Left Overlay Panel -->
		<div
			class="absolute transition-all duration-300 ease-in-out z-10 {isMinimized
				? 'left-4 top-4'
				: 'left-4 right-4 top-4 bottom-4 sm:right-auto sm:w-96 bottom-4'}"
		>
			<div class="bg-white/95 backdrop-blur-md shadow-2xl rounded-2xl border border-slate-200/50 {isMinimized ? '' : 'h-full flex flex-col'}">
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
								<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"></path>
							</svg>
						</button>
					</div>
				{:else}
					<!-- Expanded State -->
					<div class="h-full flex flex-col">
						<!-- Header with Minimize Button -->
						<div class="flex items-center justify-between px-5 py-4 border-b border-slate-200 flex-shrink-0">
							<div>
								<h1 class="text-lg font-bold text-slate-900">Projects</h1>
								{#if allProjects.length > 0}
									<p class="text-xs text-slate-500">{allProjects.length.toLocaleString()} projects</p>
								{/if}
							</div>
							<button
								onclick={toggleMinimize}
								class="p-2 hover:bg-slate-100 rounded-lg transition-colors"
								aria-label="Minimize panel"
							>
								<svg class="w-5 h-5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"></path>
								</svg>
							</button>
						</div>

						<!-- Search Input -->
						<div class="p-4 border-b border-slate-200 flex-shrink-0">
							<ProjectSearchInput {allProjects} onSelect={handleSearchSelect} />
						</div>

						<!-- Content Area (scrollable) -->
						<div class="flex-1 overflow-y-auto overflow-x-hidden">
							{#if isLoading}
								<div class="flex items-center justify-center h-32">
									<div class="flex items-center gap-2 text-slate-500 text-sm">
										<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
											<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
											<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
										</svg>
										Loading...
									</div>
								</div>
							{:else if panelView === 'building' && buildingDetails}
								<BuildingDetails building={buildingDetails} onBack={handleBackToProject} />
							{:else if panelView === 'project' && projectDetails}
								<ProjectDetails
									project={projectDetails}
									analytics={projectAnalytics}
									onBuildingSelect={handleBuildingSelect}
									onGeoPinSelect={handleGeoPinSelect}
								/>
							{:else if panelView === 'master' && masterDetails}
								<MasterProjectPanel
									master={masterDetails}
									onProjectSelect={handleProjectSelect}
								/>
							{:else}
								<div class="flex flex-col items-center justify-center h-full px-6 py-12 text-center">
									<div class="w-14 h-14 bg-slate-100 rounded-2xl flex items-center justify-center mb-4">
										<svg class="w-7 h-7 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"></path>
										</svg>
									</div>
									<h3 class="text-base font-semibold text-slate-700 mb-1">Find a Project</h3>
									<p class="text-sm text-slate-400">
										Search by project name, area, or developer
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
