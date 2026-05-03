<script lang="ts">
import { page } from '$app/state'
import LoadingState from '$lib/components/feasibility/LoadingState.svelte'
import Workspace from '$lib/components/feasibility/Workspace.svelte'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import { feasibilityStudy } from '$lib/stores/feasibilityStudy.svelte'

let loadedId = $state<number | null>(null)
let showLoading = $state(false)
const routeStudyId = $derived(Number(page.params.studyId))
const isCurrentStudyReady = $derived(
	feasibilityStudy.phase === 'ready' &&
		feasibilityStudy.savedStudyId === routeStudyId &&
		Boolean(feasibilityStudy.study)
)

$effect(() => {
	if (!Number.isFinite(routeStudyId) || routeStudyId <= 0 || loadedId === routeStudyId) return
	loadedId = routeStudyId
	void feasibilityStudy.loadSavedStudy(routeStudyId)
})

$effect(() => {
	if (isCurrentStudyReady || feasibilityStudy.phase === 'error') {
		showLoading = false
		return
	}

	showLoading = false
	const timer = setTimeout(() => {
		showLoading = true
	}, 350)
	return () => clearTimeout(timer)
})
</script>

<AppFrame>
	<PageContainer variant="fullBleed" class="h-full overflow-hidden">
		{#if isCurrentStudyReady}
			<Workspace />
		{:else if feasibilityStudy.phase === 'error'}
			<div class="grid h-full place-items-center p-6">
				<div class="max-w-md rounded-lg border border-rose-200 bg-card p-5 text-sm text-rose-700 shadow-sm">
					{feasibilityStudy.error || 'Failed to load feasibility study.'}
				</div>
			</div>
		{:else if showLoading}
			<LoadingState />
		{:else}
			<div class="h-full bg-app"></div>
		{/if}
	</PageContainer>
</AppFrame>
