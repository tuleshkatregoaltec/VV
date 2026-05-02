<script lang="ts">
import { feasibilityStudy } from '$lib/stores/feasibilityStudy.svelte'
import { feasibilityWorkspace } from '$lib/stores/feasibilityWorkspace.svelte'

import ChatPanel from './ChatPanel.svelte'
import StudyContextPanel from './StudyContextPanel.svelte'
import WorkbookPanel from './WorkbookPanel.svelte'
</script>

{#if feasibilityStudy.study}
	<div class="flex h-full min-h-0 flex-col overflow-hidden bg-background">
		<div class="flex flex-shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 py-3 shadow-xs">
			<button
				type="button"
				class="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-600 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
				onclick={() => { feasibilityStudy.reset(); feasibilityWorkspace.reset() }}
			>
				← Back to plot search
			</button>
		</div>
		<div class="grid min-h-0 flex-1 gap-4 overflow-hidden px-4 py-4 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
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
	</div>
{/if}
