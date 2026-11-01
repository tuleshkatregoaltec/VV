<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { importPollInterval } from '../../importStatus'
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
	refetchInterval: (q: { state: { dataUpdateCount: number } }) =>
		importPollInterval(processing, q.state.dataUpdateCount)
}))
</script>

<QueryView query={summary} rows={3}>
	{#snippet children(data)}
		<OwnerHistorySummary summary={data} reviewHref={listId ? `/crm/owners?scope=needs_review&list_id=${listId}` : "/crm/owners?scope=needs_review"} />
	{/snippet}
</QueryView>
