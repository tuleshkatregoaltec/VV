<script lang="ts">
import type { SourceAuditSummary } from '../../api/types'
import { fmt } from '../../format'

let { summary }: { summary: SourceAuditSummary } = $props()
const dispositionLabels: Record<string, string> = {
	latest_recorded_buyer_candidate: 'Latest recorded buyer',
	probable_owner_with_possible_financing: 'Probable owner, possible financing',
	possible_mortgage_or_bank_acquisition: 'Possible mortgage / bank acquisition',
	same_latest_party_buyer_seller: 'Same latest party recorded as buyer and seller',
	excluded_whole_building_or_project_context: 'Whole building or project context (excluded)',
	property_extent_requires_review: 'Property extent needs review',
	excluded_possible_nonownership_transaction: 'Possible non-ownership transaction (excluded)',
	latest_seller_only: 'Latest recorded party is a seller only',
	provisional_named_party_multiple_phones: 'Provisional named party with multiple phone numbers',
	latest_buyer_candidate_rounding_variants: 'Latest buyer candidate with rounding differences',
	possible_coowners_shares_unknown: 'Possible co-owners with unknown shares'
}
const sentence = (key: string) => {
	const text = key.replaceAll('_', ' ')
	return text.charAt(0).toUpperCase() + text.slice(1)
}
const matched = $derived(summary.mode === 'source_transaction_matched')
const matchCounts = $derived([
	['Source references matched to transactions', summary.matched_reference_count],
	['Distinct transaction properties matched', summary.matched_registry_property_count],
	['Unmatched source references', summary.unmatched_reference_count],
	['Ambiguous source references', summary.ambiguous_reference_count],
	['Source references excluded from matching', summary.excluded_match_reference_count],
	['Current owner–property associations', summary.current_owner_association_count],
	['Former owner–property associations', summary.former_owner_association_count]
] as const)
const counts = $derived([
	['File references', summary.reference_count],
	['Owner-candidate references', summary.owner_candidate_reference_count],
	['Possible mortgage / bank acquisition', summary.bank_reference_count],
	['Non-ownership references (excluded)', summary.excluded_nonownership_reference_count],
	['References needing review', summary.review_reference_count],
	['Out-of-scope references (excluded)', summary.excluded_scope_reference_count]
] as const)
</script>

<section class="sec source-audit" aria-label="Import summary">
	<details>
		<summary>Import summary</summary>
		{#if matched}
			<dl class="counts">
				{#each matchCounts as [label, value] (label)}
					<div><dt>{label}</dt><dd>{fmt(value ?? 0)}</dd></div>
				{/each}
			</dl>
		{/if}
		{#if matched}<h4>Reference classifications</h4>{/if}
		<p class="small muted">{fmt(summary.source_row_count ?? 0)} source rows across {fmt(summary.import_count ?? 0)} {summary.import_count === 1 ? 'import' : 'imports'}.</p>
		<dl class="counts">
			{#each counts as [label, value] (label)}
				<div><dt>{label}</dt><dd>{fmt(value ?? 0)}</dd></div>
			{/each}
		</dl>
		{#if Object.keys(summary.disposition_counts ?? {}).length}
			<details>
				<summary>By classification</summary>
				<dl class="counts dispositions">
					{#each Object.entries(summary.disposition_counts ?? {}) as [label, value] (label)}
						<div><dt>{dispositionLabels[label] ?? sentence(label)}</dt><dd>{fmt(value)}</dd></div>
					{/each}
				</dl>
			</details>
		{/if}
	</details>
</section>

<style>
	.source-audit { margin: 0.75rem 0; }
	.counts { margin: 0.75rem 0; }
	.counts > div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.45rem 0;
		border-bottom: 1px solid var(--sep);
	}
	dt { font-size: 12.5px; color: var(--text2); overflow-wrap: anywhere; }
	dd { margin: 0; font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
	summary { cursor: pointer; color: var(--text2); font-size: 12.5px; }
</style>
