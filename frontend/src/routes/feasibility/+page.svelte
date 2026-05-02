<script lang="ts">
import LoadingState from '$lib/components/feasibility/LoadingState.svelte'
import PlotSearchPanel from '$lib/components/feasibility/PlotSearchPanel.svelte'
import Workspace from '$lib/components/feasibility/Workspace.svelte'
import AppShell from '$lib/components/layout/AppShell.svelte'
import { feasibilityStudy } from '$lib/stores/feasibilityStudy.svelte'
import { feasibilityWorkspace } from '$lib/stores/feasibilityWorkspace.svelte'

$effect(() => {
	if (feasibilityStudy.phase === 'ready' && feasibilityWorkspace.chatMessages.length === 0) {
		feasibilityWorkspace.pushMessage({
			role: 'assistant',
			content: 'Seeded study ready. Ask for an explanation or propose a structured change.'
		})
	}
})
</script>

<AppShell>
	<div class="h-[calc(100vh-5rem)] overflow-hidden bg-background">
		{#if feasibilityStudy.phase === 'generating'}
			<LoadingState />
		{:else if feasibilityStudy.phase === 'ready'}
			<Workspace />
		{:else}
			<PlotSearchPanel />
		{/if}
	</div>
</AppShell>
