<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type {
	BuildingDetailResponse,
	GeoPin,
	MasterProjectResponse,
	ProjectDetailResponse,
	SearchSelection
} from '$lib/api/projects'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import ProjectMap from '$lib/components/map/ProjectMap.svelte'
import BuildingDetails from '$lib/components/projects/BuildingDetails.svelte'
import MasterProjectPanel from '$lib/components/projects/MasterProjectPanel.svelte'
import ProjectDetails from '$lib/components/projects/ProjectDetails.svelte'
import ProjectSearchInput from '$lib/components/projects/ProjectSearchInput.svelte'
import { projectQueries } from '$lib/queries/projects'

let isMinimized = $state(false)
let panelView = $state<'empty' | 'project' | 'building' | 'master'>('empty')
let mapComponent = $state<any>()
let selectedMasterName = $state<string | null>(null)
let selectedProjectId = $state<number | null>(null)
let selectedBuildingId = $state<number | null>(null)
let ddaPlotsVisible = $state(true)

const allProjectsQuery = createQuery(() => projectQueries.list())
const masterDetailsQuery = createQuery(() =>
	projectQueries.master(panelView === 'master' ? selectedMasterName : null)
)
const projectDetailsQuery = createQuery(() =>
	projectQueries.detail(panelView === 'project' ? selectedProjectId : null)
)
const buildingDetailsQuery = createQuery(() =>
	projectQueries.building(panelView === 'building' ? selectedBuildingId : null)
)

let allProjects = $derived(allProjectsQuery.data ?? [])
const masterDetails = $derived<MasterProjectResponse | null>(masterDetailsQuery.data ?? null)
const projectDetails = $derived<ProjectDetailResponse | null>(projectDetailsQuery.data ?? null)
const buildingDetails = $derived<BuildingDetailResponse | null>(buildingDetailsQuery.data ?? null)

const ddaAreaName = $derived<string | null>(
	panelView === 'project' && projectDetails
		? projectDetails.area_name
		: panelView === 'master' && masterDetails
			? masterDetails.area_name
			: null
)

const ddaPlotsQuery = createQuery(() => projectQueries.ddaPlots(ddaAreaName))
const ddaPlots = $derived(ddaPlotsQuery.data ?? [])

const isLoading = $derived.by(() => {
	if (panelView === 'master') return masterDetailsQuery.isPending || masterDetailsQuery.isFetching
	if (panelView === 'project')
		return projectDetailsQuery.isPending || projectDetailsQuery.isFetching
	if (panelView === 'building') {
		return buildingDetailsQuery.isPending || buildingDetailsQuery.isFetching
	}
	return allProjectsQuery.isPending
})

function handleSearchSelect(sel: SearchSelection) {
	if (sel.type === 'master') {
		handleMasterSelect(sel.masterName)
	} else {
		handleProjectSelect(sel.projectId)
	}
}

function handleMasterSelect(masterName: string) {
	selectedMasterName = masterName
	selectedProjectId = null
	selectedBuildingId = null
	panelView = 'master'
}

function handleProjectSelect(projectId: number) {
	selectedProjectId = projectId
	selectedMasterName = null
	selectedBuildingId = null
	panelView = 'project'
}

function handleBuildingSelect(propertyId: number, lng?: number, lat?: number) {
	selectedBuildingId = propertyId
	panelView = 'building'

	if (lng && lat && mapComponent) {
		mapComponent.flyToLocation(lng, lat, 17)
	}
}

function handleBuildingPinClick(pin: GeoPin) {
	if (pin.property_id) {
		handleBuildingSelect(pin.property_id, pin.longitude, pin.latitude)
	} else {
		mapComponent?.flyToLocation(pin.longitude, pin.latitude, 17)
	}
}

function handleGeoPinSelect(lat: number, lng: number) {
	if (mapComponent) mapComponent.flyToLocation(lng, lat, 17)
}

function handleBackToProject() {
	selectedBuildingId = null
	panelView = 'project'
}

function toggleMinimize() {
	isMinimized = !isMinimized
}

$effect(() => {
	if (!masterDetails || !mapComponent || masterDetails.geo_pins.length === 0) return
	mapComponent.fitBounds(masterDetails.geo_pins)
})

$effect(() => {
	if (!projectDetails || !mapComponent) return
	mapComponent.flyToProject(
		projectDetails.project_id,
		projectDetails.project_name,
		projectDetails.latitude,
		projectDetails.longitude,
		projectDetails.area_polygon,
		projectDetails.geo_pins ?? [],
		13
	)
})

$effect(() => {
	if (!mapComponent) return
	if (ddaPlotsVisible && ddaPlots.length > 0) {
		mapComponent.showDDAPlots(ddaPlots)
	} else {
		mapComponent.hideDDAPlots()
	}
})
</script>

<AppFrame>
	<PageContainer variant="fullBleed" class="h-full overflow-hidden">
		<div class="relative h-full overflow-hidden">
		<!-- Map (full screen) -->
		<div class="absolute inset-0">
			<ProjectMap
				bind:this={mapComponent}
				onProjectSelect={handleProjectSelect}
				onBuildingPinClick={handleBuildingPinClick}
			/>
		</div>

		<!-- DDA Plots layer toggle — bottom-right of map -->
		{#if ddaAreaName}
			<div class="absolute bottom-6 right-4 z-10">
				<button
					type="button"
					onclick={() => (ddaPlotsVisible = !ddaPlotsVisible)}
					class="flex items-center gap-2 rounded-lg border bg-white px-3 py-2 text-xs font-medium shadow-md transition-colors {ddaPlotsVisible
						? 'border-amber-300 text-amber-800'
						: 'border-border text-fg-3'}"
				>
					<span
						class="inline-block h-2.5 w-2.5 flex-shrink-0 rounded-sm {ddaPlotsVisible
							? 'bg-amber-400'
							: 'bg-slate-300'}"
					></span>
					DDA plots
					{#if ddaPlots.length > 0}
						<span class="text-[10px] text-fg-4">({ddaPlots.length})</span>
					{/if}
				</button>
			</div>
		{/if}

		<!-- Floating Left Overlay Panel -->
		<div
			class="absolute transition-all duration-300 ease-in-out z-10 {isMinimized
				? 'left-4 top-4'
				: 'left-4 right-4 top-4 bottom-4 sm:right-auto sm:w-96 bottom-4'}"
		>
			<div
				class="bg-white shadow-lg rounded-lg border border-border {isMinimized
					? ''
					: 'h-full flex flex-col'}"
			>
				{#if isMinimized}
					<!-- Minimized State -->
					<div class="flex items-center gap-2 px-4 py-3">
						<span class="text-sm font-semibold text-slate-900 whitespace-nowrap">Projects</span>
						<button
							onclick={toggleMinimize}
							class="p-1.5 hover:bg-slate-100 transition-colors rounded-lg flex-shrink-0"
							aria-label="Expand panel"
						>
							<svg
								class="w-4 h-4 text-slate-600"
								fill="none"
								stroke="currentColor"
								viewBox="0 0 24 24"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									stroke-width="2"
									d="M9 5l7 7-7 7"
								></path>
							</svg>
						</button>
					</div>
				{:else}
					<!-- Expanded State -->
					<div class="h-full flex flex-col">
						<!-- Header with Minimize Button -->
						<div
							class="flex items-center justify-between px-5 py-4 border-b border-slate-200 flex-shrink-0"
						>
							<div>
								<h1 class="text-lg font-semibold text-fg-1">Projects</h1>
								{#if allProjects.length > 0}
									<p class="text-xs text-slate-500">
										{allProjects.length.toLocaleString()} projects
									</p>
								{/if}
							</div>
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
						<div class="p-4 border-b border-slate-200 flex-shrink-0">
							<ProjectSearchInput {allProjects} onSelect={handleSearchSelect} />
						</div>

						<!-- Content Area (scrollable) -->
						<div class="flex-1 overflow-y-auto overflow-x-hidden">
							{#if isLoading}
								<div class="flex items-center justify-center h-32">
									<div class="flex items-center gap-2 text-slate-500 text-sm">
										<svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
											<circle
												class="opacity-25"
												cx="12"
												cy="12"
												r="10"
												stroke="currentColor"
												stroke-width="4"
											></circle>
											<path
												class="opacity-75"
												fill="currentColor"
												d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
											></path>
										</svg>
										Loading...
									</div>
								</div>
							{:else if panelView === 'building' && buildingDetails}
								<BuildingDetails building={buildingDetails} onBack={handleBackToProject} />
							{:else if panelView === 'project' && projectDetails}
								<ProjectDetails
									project={projectDetails}
									onBuildingSelect={handleBuildingSelect}
									onGeoPinSelect={handleGeoPinSelect}
								/>
							{:else if panelView === 'master' && masterDetails}
								<MasterProjectPanel master={masterDetails} onProjectSelect={handleProjectSelect} />
							{:else}
								<div
									class="flex flex-col items-center justify-center h-full px-6 py-12 text-center"
								>
									<div
										class="w-14 h-14 bg-slate-100 rounded-lg flex items-center justify-center mb-4"
									>
										<svg
											class="w-7 h-7 text-slate-400"
											fill="none"
											stroke="currentColor"
											viewBox="0 0 24 24"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-2 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"
											></path>
										</svg>
									</div>
									<h3 class="text-base font-semibold text-slate-700 mb-1">Find a Project</h3>
									<p class="text-sm text-slate-400">Search by project name, area, or developer</p>
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</div>
		</div>
	</PageContainer>
</AppFrame>
