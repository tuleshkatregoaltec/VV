<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Search from 'lucide-svelte/icons/search'
import { aed, fmt, fullDate } from '../../format'
import {
	clampOffset,
	explainMatch,
	fieldLabel,
	MATCH_FILTERS,
	type MatchFilterId,
	matchedSaleLine,
	matchOutcomeInfo,
	STATUS_INFO
} from '../../ownerImportReport'
import { crmQueries } from '../../queries'
import { openOwner } from '../../stores/panel.svelte'
import Chip from '../ui/Chip.svelte'
import QueryView from '../ui/QueryView.svelte'
import Tabs from '../ui/Tabs.svelte'

/**
 * The kept rows of one owner file, 100 at a time, filtered by match colour and searched by name,
 * phone, building or unit. Each row shows the owner, the property the sheet names, the matcher's
 * outcome, the sale it tied the row to and why, in plain words. The result tabs sit above the
 * search, as on the mock's Owners screen. Rows of an import that has not been
 * re-matched yet carry no outcome; they show their ownership status and reason instead, and the
 * colour chips are hidden (`matched` is false). Changing the filter or the search goes back to the
 * first page; while the new page loads the old rows are dimmed and the pager waits. The search stops
 * at 160 characters, the backend's limit. A row opens its owner, on the row's unit.
 */
let {
	listId,
	filter = $bindable('all'),
	matched = true
}: { listId: number; filter?: MatchFilterId; matched?: boolean } = $props()

let typed = $state('')
let search = $state('')
let offset = $state(0)

$effect(() => {
	const v = typed.trim()
	const t = setTimeout(() => (search = v), 300)
	return () => clearTimeout(t)
})
// Back to the first page whenever the filter or the search changes.
$effect.pre(() => {
	void filter
	void search
	offset = 0
})

const picked = $derived(MATCH_FILTERS.find((f) => f.id === filter))
const rows = createQuery(() =>
	crmQueries.ownerImportRows(listId, {
		status: null,
		matchColour: matched ? (picked?.colours ?? []) : [],
		matchOutcome: matched ? (picked?.outcomes ?? []) : [],
		search,
		offset
	})
)
const loading = $derived(rows.isPlaceholderData)

// After a refresh with fewer rows, step back to the last page that still has rows.
$effect(() => {
	const d = rows.data
	if (!d || loading) return
	const next = clampOffset(offset, d.total, d.limit)
	if (next !== offset) offset = next
})
const usable = (value: string | undefined) =>
	value && !['0', 'null', 'none', 'n/a', '-'].includes(value.trim().toLowerCase()) ? value : ''
</script>

{#if matched}
	<Tabs label="Show rows by result" items={MATCH_FILTERS} value={filter} onselect={(id) => (filter = id)} />
{/if}
<div class="filters">
	<label class="search">
		<Search size={15} />
		<span class="sr-only">Search rows</span>
		<input placeholder="Name, phone, building, unit" autocomplete="off" maxlength="160" bind:value={typed} />
	</label>
	{#if rows.data}
		<span class="count" aria-live="polite">
			{loading
				? 'Loading…'
				: rows.data.total
				? `Showing ${fmt(rows.data.offset + 1)}–${fmt(rows.data.offset + rows.data.rows.length)} of ${fmt(rows.data.total)}`
				: 'No rows'}
		</span>
	{/if}
</div>

<QueryView query={rows} rows={6}>
	{#snippet children(page)}
		<div class={['card', loading && 'stale']} aria-busy={loading}>
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Owner</th>
							<th>Property in the sheet</th>
							<th>Result</th>
							<th>Matched sale</th>
							<th>Why</th>
						</tr>
					</thead>
					<tbody>
						{#each page.rows as r (r.id)}
							{@const outcome = matchOutcomeInfo(r.matchOutcome, r.matchColour)}
							{@const sale = matchedSaleLine(r.matchedSale)}
							{@const reasons = (r.matchReasons ?? []).map(explainMatch).filter(Boolean)}
							{@const warnings = (r.matchWarnings ?? []).map(explainMatch).filter(Boolean)}
							<tr class="row">
								<td>
									<button type="button" class="rowlink nm" onclick={() => openOwner(r.ownerKey, r.unit)}>
										{r.name}
									</button>
									<div class="sub mono">{r.phone || '—'}</div>
								</td>
								<td data-label="Property"><div class="cell">
									{usable(r.building) || '—'}{r.unit ? ` · ${r.unit}` : ''}
									<div class="sub">
										{[usable(r.project) !== usable(r.building) ? usable(r.project) : '', usable(r.area)].filter(Boolean).join(' · ') || 'No project identified'}
									</div>
									<div class="sub">
										{r.price ? aed(r.price) : 'No price'}{r.date ? ` · ${fullDate(r.date)}` : ''} · Sheet {r.sheet}, row {r.rowNumber}
									</div>
								</div></td>
								<td data-label="Result"><div class="cell">
									{#if outcome}
										<Chip tone={outcome.tone}>{outcome.label}</Chip>
									{:else}
										<Chip tone={STATUS_INFO[r.status].tone}>{STATUS_INFO[r.status].label}</Chip>
									{/if}
								</div></td>
								<td data-label="Matched sale" class="sale"><div class="cell">
									{#if sale}{sale}{:else}<span class="sub">{outcome ? 'No sale' : '—'}</span>{/if}
								</div></td>
								<td data-label="Why" class="why"><div class="cell">
									{#if outcome}
										{#each reasons as t, n (n)}<div>{t}</div>{:else}<span class="sub">—</span>{/each}
										{#each warnings as t, n (n)}<div class="warn">{t}</div>{/each}
									{:else}
										{r.reason || '—'}
									{/if}
									<details class="sub">
										<summary>Details</summary>
										<div>{STATUS_INFO[r.status].label}</div>
										{#if r.latestSaleDate}<div>Latest sale: {fullDate(r.latestSaleDate)}{r.latestSalePrice ? ` · ${aed(r.latestSalePrice)}` : ''}</div>{/if}
										{#each Object.entries(r.propertyDetails).filter(([key, value]) => key.startsWith('source_') && usable(value)) as [key, value] (key)}
											<div>{fieldLabel(key.replace('source_', ''))}: {value}</div>
										{/each}
										{#if r.propertyDetails.matched_sale_date}<div>Matched sale: {fullDate(r.propertyDetails.matched_sale_date)}</div>{/if}
									</details>
								</div></td>
							</tr>
						{:else}
							<tr><td colspan="5" class="sub">No rows match.</td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{#if page.total > page.limit}
			<div class="pager">
				<button
					type="button"
					class="btn ghost sm"
					disabled={loading || offset === 0}
					onclick={() => (offset = Math.max(0, offset - page.limit))}
				>
					Previous
				</button>
				<button
					type="button"
					class="btn ghost sm"
					disabled={loading || offset + page.limit >= page.total}
					onclick={() => (offset = offset + page.limit)}
				>
					Next
				</button>
			</div>
		{/if}
	{/snippet}
</QueryView>

<style>
	.why,
	.sale {
		max-width: 26rem;
		font-size: 12.5px;
	}
	.cell {
		min-width: 0;
	}
	.why .cell > div + div {
		margin-top: 0.15rem;
	}
	.why .warn {
		color: var(--amber);
	}
	.stale {
		opacity: 0.55;
		transition: opacity 0.15s;
	}
	.pager {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		margin-top: 0.75rem;
	}
	@media (max-width: 700px) {
		.why,
		.sale {
			max-width: none;
		}
		.cell {
			text-align: right;
		}
	}
</style>
