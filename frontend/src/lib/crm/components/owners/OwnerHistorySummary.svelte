<script lang="ts">
import type { OwnerHistorySummary } from '../../api/types'
import { fmt } from '../../format'

let {
	summary,
	reviewHref = '/crm/owners?scope=needs_review'
}: { summary: OwnerHistorySummary; reviewHref?: string } = $props()
const sourceOnly = $derived(summary.warehouse_status === 'not_requested')
const counts = $derived([
	['Properties identified', summary.identifiable_property_count],
	[
		sourceOnly ? 'Owner–property associations' : 'Owner–property links',
		summary.owner_property_count
	],
	[sourceOnly ? 'Buyer transaction matches' : 'Current owners', summary.verified_current_count],
	['Possible current owners', summary.probable_current_count],
	['Former owners', summary.former_count],
	[sourceOnly ? 'Other associations' : 'Links needing review', summary.unresolved_count]
] as const)
const sourceCounts = $derived([
	['Source events', summary.source_event_count],
	['Events without a property match', summary.invalid_identity_source_count]
] as const)
</script>

<section class="sec ownership-summary" aria-label="Current ownership summary">
	{#if summary.warehouse_status === 'unavailable'}
		<p class="notice" role="status">Transaction data is unavailable right now.</p>
	{/if}
	{#if !sourceOnly && (summary.unresolved_count || summary.invalid_identity_source_count)}
		<div class="review">
			<a class="btn ghost sm" href={reviewHref}>Review unresolved owners</a>
		</div>
	{/if}
	<details class="technical">
		<summary>Details</summary>
		<dl class="counts">
			{#each counts as [label, value] (label)}
				<div><dt>{label}</dt><dd>{fmt(value)}</dd></div>
			{/each}
		</dl>
		<dl class="counts">
			{#each sourceCounts as [label, value] (label)}
				<div><dt>{label}</dt><dd>{fmt(value)}</dd></div>
			{/each}
		</dl>
	</details>
</section>

<style>
	.ownership-summary { margin: 0.75rem 0; }
	.notice { margin: 0 0 0.5rem; }
	.counts { margin: 0.75rem 0; }
	.counts > div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.45rem 0;
		border-bottom: 1px solid var(--sep);
	}
	dt { font-size: 12.5px; color: var(--text2); }
	dd { margin: 0; font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
	.review { display: flex; flex-wrap: wrap; align-items: center; gap: 0.75rem; margin: 0.5rem 0; }
	.technical summary { cursor: pointer; color: var(--text2); font-size: 12.5px; }
</style>
