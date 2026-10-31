<script lang="ts">
import type { OwnerHistorySummary } from '../../api/types'
import { fmt } from '../../format'

let {
	summary,
	scope,
	reviewHref = '/crm/owners?scope=needs_review'
}: { summary: OwnerHistorySummary; scope: string; reviewHref?: string } = $props()
const sourceOnly = $derived(summary.warehouse_status === 'not_requested')
const counts = $derived([
	[
		sourceOnly ? 'Identified source property groups' : 'Properties identified',
		summary.identifiable_property_count
	],
	[sourceOnly ? 'Source associations' : 'People–property links', summary.owner_property_count],
	[
		sourceOnly ? 'Buyer transaction matches (not checked)' : 'Transaction-matched current buyers',
		summary.verified_current_count
	],
	[
		sourceOnly ? 'Possible owner associations' : 'Possible current owners',
		summary.probable_current_count
	],
	[
		sourceOnly ? 'Former-owner associations (not rechecked)' : 'Former owner associations',
		summary.former_count
	],
	[
		sourceOnly ? 'Other historical/source associations' : 'Links needing review',
		summary.unresolved_count
	]
] as const)
const sourceCounts = $derived([
	['Source events', summary.source_event_count],
	['Events without a reliable property identity', summary.invalid_identity_source_count],
	['Rows from earlier import rules', summary.legacy_source_event_count]
] as const)
</script>

<section class="sec ownership-summary" aria-label="Current ownership summary">
	{#if sourceOnly}
		<p class="notice" role="status">Workbook only — transaction matching not run. Sales evidence was not checked. These are source-based candidate assessments; current ownership is unverified.</p>
	{:else if summary.warehouse_status === 'unavailable'}
		<p class="notice" role="status">Sales evidence is temporarily unavailable. These assessments use imported evidence only; current ownership cannot be checked against available sales. Review before relying on them.</p>
	{:else if summary.checked_at}
		<p class="small muted">Checked against available sales {new Date(summary.checked_at).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}.</p>
	{/if}
	{#if !sourceOnly && (summary.unresolved_count || summary.invalid_identity_source_count)}
		<div class="review">
			<a class="btn ghost sm" href={reviewHref}>Review people with unresolved evidence</a>
			<span class="small muted">Open a person to inspect source rows and record a review note.</span>
		</div>
	{/if}
	<details class="technical">
		<summary>Evidence and counting details</summary>
		<p class="small muted">{scope}</p>
		<dl class="counts">
			{#each counts as [label, value] (label)}
				<div><dt>{label}</dt><dd>{fmt(value)}</dd></div>
			{/each}
		</dl>
		{#if sourceOnly}
			<p class="small muted">These counts retain historical/source associations across imported rows, not unique people or workbook references. Other historical/source associations are not additional reference-review cases. The Workbook source audit gives the audited reference classifications and the number of references needing review.</p>
		{:else}
			<p class="small muted">These are people–property links, not unique people. One property can have several associated people. A transaction match supports the imported buyer’s claim; available sales do not independently verify the named person’s legal ownership. Possible owners have lower evidence scores; date or party-role uncertainty remains visible for review.</p>
		{/if}
		{#if summary.invalid_identity_source_count}
			<p class="small muted">{fmt(summary.invalid_identity_source_count)} source records need property details before a reliable people–property link can be counted. {sourceOnly ? 'They remain in source history and do not add reference-review cases.' : 'These records also appear in the review queue.'}</p>
		{/if}
		{#if summary.unverified_former_count}
			{#if sourceOnly}
				<p class="small muted">{fmt(summary.unverified_former_count)} historical seller-claim associations remain in source history; these do not add reference-review cases.</p>
			{:else}
				<p class="small muted">{fmt(summary.unverified_former_count)} seller claims are included in links needing review. A seller label alone does not establish a former owner.</p>
			{/if}
		{/if}
		<dl class="counts">
			{#each sourceCounts as [label, value] (label)}
				<div><dt>{label}</dt><dd>{fmt(value)}</dd></div>
			{/each}
		</dl>
		{#if sourceOnly}
			<p class="small muted">Repeated rows across files do not establish separate transactions. Historical events and records with incomplete property identity remain visible in source history. Transaction matching was not requested for this view.</p>
		{:else}
			<p class="small muted">Repeated rows across files do not add new people–property links or establish separate transactions. Events with invalid property identity remain in history and are excluded from property and link totals. Earlier import versions describe how the source was loaded; the current assessment rechecks the available evidence using today’s rules.</p>
		{/if}
		{#if summary.assessment_version}<p class="small muted">Assessment version: {summary.assessment_version}</p>{/if}
		{#if Object.keys(summary.resolver_versions ?? {}).length}
			<p class="small muted">Source resolver coverage: {Object.entries(summary.resolver_versions ?? {}).map(([version, count]) => `${version}: ${fmt(count)}`).join(' · ')}</p>
		{/if}
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
