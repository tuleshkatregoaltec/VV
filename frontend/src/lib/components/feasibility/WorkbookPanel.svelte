<script lang="ts">
import { workbookStore } from '$lib/stores/workbookStore.svelte'
import SpreadsheetPanel from './SpreadsheetPanel.svelte'
</script>

{#if workbookStore.study}
	<div class="h-full overflow-hidden rounded-xl border border-[var(--color-border)] bg-white">
		<SpreadsheetPanel />
	</div>
{/if}
