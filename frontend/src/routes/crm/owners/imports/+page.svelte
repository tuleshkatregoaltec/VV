<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import Upload from 'lucide-svelte/icons/upload'
import { goto } from '$app/navigation'
import type { OwnerImportDetail } from '$lib/crm/api/types'
import OwnerImportSummary from '$lib/crm/components/owners/OwnerImportSummary.svelte'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import InfoTip from '$lib/crm/components/ui/InfoTip.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt, plural } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { panel } from '$lib/crm/stores/panel.svelte'

/**
 * Owner files: one row per file with what it held, how many of its distinct units were mapped to
 * a sale, when it was imported and its status. ⚠ marks a failed import or a sheet whose mapping
 * dropped rows or left them without a property. The org-wide ownership summary sits below.
 */
const imports = createQuery(() => crmQueries.ownerImportDetails())

const STATUS = {
	completed: { label: 'Completed', tone: 'green' },
	processing: { label: 'Processing', tone: 'amber' },
	failed: { label: 'Failed', tone: 'red' }
} as const

/** "Completed · 30,312 kept · 62 dropped". */
function statusText(i: OwnerImportDetail) {
	if (i.status !== 'completed') return STATUS[i.status].label
	const c = i.counts
	return [
		'Completed',
		`${fmt(c.kept)} kept`,
		c.merged ? `${fmt(c.merged)} duplicates merged` : '',
		c.dropped ? `${fmt(c.dropped)} dropped` : ''
	]
		.filter(Boolean)
		.join(' · ')
}

/** The header's facts: files, rows and units mapped across completed files. */
function facts(list: OwnerImportDetail[] | undefined) {
	if (!list?.length) return ''
	const done = list.filter((i) => i.status === 'completed')
	const rows = done.reduce((t, i) => t + i.counts.rows, 0)
	const matched = done.flatMap((i) => (i.counts.ownerMatch ? [i.counts.ownerMatch.headline] : []))
	const units = matched.reduce((t, h) => t + h.units, 0)
	const total = matched.reduce((t, h) => t + h.total, 0)
	return [
		plural(list.length, 'file'),
		`${fmt(rows)} rows`,
		total ? `${fmt(units)} of ${fmt(total)} units mapped` : ''
	]
		.filter(Boolean)
		.join(' · ')
}

/** Why an import is flagged: the failure, then each sheet's error-level mapping checks. */
const problems = (i: OwnerImportDetail) => [
	...(i.status === 'failed' ? [{ sheet: '', text: 'The import failed.' }] : []),
	...i.sheets.flatMap((s) =>
		s.checks.filter((c) => c.level === 'error').map((c) => ({ sheet: s.name, text: c.text }))
	)
]
const upload = () => panel.open({ kind: 'new-import', ownersOnly: true })
</script>

<svelte:head><title>Owner imports · CRM</title></svelte:head>

<PageHeader title="Owner imports" facts={facts(imports.data)}>
	{#snippet right()}
		<a class="btn ghost" href="/crm/owners"><ArrowLeft size={15} /><span>Owners</span></a>
		<button type="button" class="btn" onclick={upload}><Upload size={15} /><span>Upload</span></button>
	{/snippet}
</PageHeader>

<section class="card" aria-labelledby="files-h">
	<div class="ch">
		<h2 id="files-h">Owner files</h2>
		<button type="button" class="btn ghost sm" onclick={upload}>Import a file</button>
	</div>
	<QueryView query={imports} rows={6}>
		{#snippet children(list)}
			{#if !list.length}
				<Empty text="No owner files imported yet." />
			{:else}
				<div class="tblwrap">
					<table class="tbl">
						<thead>
							<tr>
								<th>File</th>
								<th>What</th>
								<th>Units mapped</th>
								<th>Imported</th>
								<th>Status</th>
							</tr>
						</thead>
						<tbody>
							{#each list as i (i.id)}
								<tr class="row">
									<td>
										<button type="button" class="rowlink" onclick={() => goto(`/crm/owners/imports/${i.id}`)}>
											{i.name}
										</button>
										<div class="sub mono">{i.file}</div>
									</td>
									<td data-label="What" class="nowrap">
										Owners{i.status === 'completed' ? ` · ${fmt(i.counts.rows)} rows` : ''}
									</td>
									<td data-label="Units mapped" class="nowrap">
										{#if i.status !== 'completed'}
											<span class="sub">—</span>
										{:else if i.counts.ownerMatch}
											{@const h = i.counts.ownerMatch.headline}
											<b class="uc">{h.percent}%</b> <span class="sub">{fmt(h.units)} of {fmt(h.total)}</span>
										{:else}
											<span class="sub">Re-match pending</span>
										{/if}
									</td>
									<td data-label="Imported" class="nowrap">{i.at}</td>
									<td data-label="Status">
										<span class="st">
											<Chip tone={STATUS[i.status].tone}>{statusText(i)}</Chip>
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
										</span>
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{/if}
		{/snippet}
	</QueryView>
</section>

<section class="sec org" aria-label="Ownership across all imports">
	<h3>Ownership across all imports</h3>
	<OwnerImportSummary processing={imports.data?.some((i) => i.status === 'processing')} />
</section>

<style>
	.uc {
		font-variant-numeric: tabular-nums;
	}
	.st {
		display: inline-flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.probs {
		margin: 0;
		padding-left: 1.1rem;
		display: grid;
		gap: 0.3rem;
	}
	.probs .sheet {
		font-weight: 600;
	}
	.org {
		margin-top: 1.5rem;
	}
</style>
