<script lang="ts">
import { workbookStore } from '$lib/stores/workbookStore.svelte'
import SpreadsheetPanel from './SpreadsheetPanel.svelte'
</script>

{#if workbookStore.study}
	<div class="h-full overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm">
		<SpreadsheetPanel />
	</div>
{/if}
