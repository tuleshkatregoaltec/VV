<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import Upload from 'lucide-svelte/icons/upload'
import { goto } from '$app/navigation'
import type { OwnerImportDetail } from '$lib/crm/api/types'
import OwnerImportSummary from '$lib/crm/components/owners/OwnerImportSummary.svelte'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import InfoTip from '$lib/crm/components/ui/InfoTip.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { panel } from '$lib/crm/stores/panel.svelte'

/**
 * Owner imports: source records kept, explicit registry property links and dropped rows.
 * so a manager can see which files need fixing. ⚠ marks a failed import or a sheet whose mapping
 * means its rows were dropped or can't be tied to a property. Totals count completed imports.
 */
const imports = createQuery(() => crmQueries.ownerImportDetails())

const STATUS = {
	completed: { label: 'Completed', tone: 'green' },
	processing: { label: 'Processing', tone: 'amber' },
	failed: { label: 'Failed', tone: 'red' }
} as const

function totals(list: OwnerImportDetail[]) {
	const done = list.filter((i) => i.status === 'completed')
	const sum = (k: 'rows' | 'kept' | 'merged' | 'dropped') =>
		done.reduce((t, i) => t + i.counts[k], 0)
	return [
		{ label: 'Imports', v: list.length },
		{ label: 'Source rows', v: sum('rows') },
		{ label: 'Source records kept', v: sum('kept') },
		{ label: 'Duplicate rows merged', v: sum('merged') },
		{ label: 'Dropped rows', v: sum('dropped') }
	]
}

/** Why an import is flagged: the failure, then each sheet's error-level mapping checks. */
const problems = (i: OwnerImportDetail) => [
	...(i.status === 'failed' ? [{ sheet: '', text: 'The import failed.' }] : []),
	...i.sheets.flatMap((s) =>
		s.checks.filter((c) => c.level === 'error').map((c) => ({ sheet: s.name, text: c.text }))
	)
]
</script>

<svelte:head><title>Owner imports · CRM Beta</title></svelte:head>

<PageHeader title="Owner imports" facts="Upload files and review their processing reports">
	{#snippet right()}
		<a class="btn ghost" href="/crm/owners"><ArrowLeft size={15} /><span>Owners</span></a>
		<button type="button" class="btn ghost" onclick={() => panel.open({ kind: 'new-import', ownersOnly: true })}>
			<Upload size={15} /><span>Upload</span>
		</button>
	{/snippet}
</PageHeader>

<OwnerImportSummary processing={imports.data?.some((i) => i.status === 'processing')} />

<QueryView query={imports} rows={6}>
	{#snippet children(list)}
		{#if !list.length}
			<div class="card empty-imports">
				<p>No owner files imported yet.</p>
				<button type="button" class="btn" onclick={() => panel.open({ kind: 'new-import', ownersOnly: true })}>
					<Upload size={15} /><span>Upload</span>
				</button>
			</div>
		{:else}

			<p class="hint">Completed files: source rows = kept + merged + dropped. Open a file to review its records and ownership evidence.</p>
			<div class="card">
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>Import</th>
								<th>Date</th>
								<th class="r">Rows</th>
								<th class="r">Kept</th>
								<th class="r">Merged</th>
								<th class="r">Dropped</th>
								<th class="r">Units confirmed</th>
								<th>Status</th>
								<th><span class="sr-only">Problems</span></th>
							</tr>
						</thead>
						<tbody>
							{#each list as i (i.id)}
								<tr class="row">
									<td>
										<button type="button" class="rowlink" onclick={() => goto(`/crm/owners/imports/${i.id}`)}>
											{i.name}
										</button>
										<div class="sub">{i.file}</div>
										{#if i.status === 'completed' && i.counts.rows !== i.counts.kept + i.counts.merged + i.counts.dropped}
											<div class="sub">Row totals need review</div>
										{/if}
									</td>
									<td data-label="Date" class="nowrap">{i.at}</td>
									<td data-label="Rows" class="r">{i.status === 'completed' ? fmt(i.counts.rows) : '—'}</td>
									<td data-label="Kept" class="r">{i.status === 'completed' ? fmt(i.counts.kept) : '—'}</td>
									<td data-label="Merged" class="r">{i.status === 'completed' ? fmt(i.counts.merged) : '—'}</td>
									<td data-label="Dropped" class="r">{i.status === 'completed' ? fmt(i.counts.dropped) : '—'}</td>
									<td data-label="Units confirmed" class="r">
										{#if i.status !== 'completed'}
											—
										{:else if i.counts.ownerMatch}
											{@const h = i.counts.ownerMatch.headline}
											<span class="uc">{h.percent}%</span> <span class="sub">of {fmt(h.total)}</span>
										{:else}
											<span class="sub">Re-match pending</span>
										{/if}
									</td>
									<td data-label="Status"><Chip tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Chip></td>
									<td data-label="Problems">
										{#if i.flagged}
											<InfoTip label="Why {i.name} needs a look" glyph="⚠" tone="amber">
												<b>Needs a look</b>
												<ul class="probs">
													{#each problems(i) as p, n (n)}
														<li>{#if p.sheet}<span class="sheet">{p.sheet}:</span>{/if} {p.text}</li>
													{/each}
												</ul>
											</InfoTip>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			</div>
			<details class="snapshot">
				<summary>Import-time processing totals · historical</summary>
			<div class="totals">
				{#each totals(list) as t (t.label)}
					<div class="total">
						<span class="label">{t.label}</span>
						<span class="v">{t.v === null ? '—' : fmt(t.v)}</span>
					</div>
				{/each}
			</div>
			<p class="hint">Row totals cover completed imports at processing time. Property links and people are counted separately in each report’s evidence details.</p>

			</details>
		{/if}
	{/snippet}
</QueryView>

<style>
	.snapshot { margin: 1rem 0; }
	.snapshot > summary { cursor: pointer; margin-bottom: 0.75rem; }
	.totals { margin: 0.75rem 0; }
	.total { display: flex; justify-content: space-between; gap: 1rem; padding: 0.45rem 0; border-bottom: 1px solid var(--sep); font-size: 12.5px; }
	.label { color: var(--text2); }
	.uc { font-weight: 600; font-variant-numeric: tabular-nums; }
	.v { font-variant-numeric: tabular-nums; font-weight: 600; }
	.probs {
		margin: 0;
		padding-left: 1.1rem;
		display: grid;
		gap: 0.3rem;
	}
	.probs .sheet {
		font-weight: 600;
	}
	.hint {
		color: var(--text2);
		font-size: 12px;
	}
	.empty-imports {
		display: grid;
		justify-items: start;
		gap: 0.75rem;
		padding: 1.25rem;
	}
</style>
