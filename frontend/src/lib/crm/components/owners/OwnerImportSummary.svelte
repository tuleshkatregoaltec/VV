<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crmQueries } from '../../queries'
import QueryView from '../ui/QueryView.svelte'
import OwnerHistorySummary from './OwnerHistorySummary.svelte'

let {
	importId,
	listId,
	processing = false
}: { importId?: number; listId?: number | null; processing?: boolean } = $props()
const summary = createQuery(() => ({
	...crmQueries.ownerHistorySummary(importId),
	refetchInterval: processing ? 5000 : false
}))
</script>

<QueryView query={summary} rows={3}>
	{#snippet children(data)}
		<OwnerHistorySummary summary={data} reviewHref={listId ? `/crm/owners?scope=needs_review&list_id=${listId}` : "/crm/owners?scope=needs_review"} scope={importId === undefined
			? 'Across all owner imports in your organization.'
			: 'People and properties recorded in this import, assessed using evidence across all owner imports.'} />
	{/snippet}
</QueryView>
