<script lang="ts">
import { workbookStore } from '$lib/stores/workbookStore.svelte'

import ChatPanel from './ChatPanel.svelte'
import StudyContextPanel from './StudyContextPanel.svelte'
import WorkbookPanel from './WorkbookPanel.svelte'
</script>

{#if workbookStore.study}
	<div class="grid h-full min-h-0 gap-6 overflow-hidden px-6 py-6 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
		<div class="min-h-0 overflow-auto">
			<StudyContextPanel />
		</div>
		<div class="min-h-0 overflow-hidden">
			<WorkbookPanel />
		</div>
		<div class="min-h-0 overflow-hidden">
			<ChatPanel />
		</div>
	</div>
{/if}
