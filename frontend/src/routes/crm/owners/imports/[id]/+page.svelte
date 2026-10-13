<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { crm } from '$lib/crm/api'
import type { OwnerImportDetail } from '$lib/crm/api/types'
import ImportRows from '$lib/crm/components/imports/ImportRows.svelte'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import InfoTip from '$lib/crm/components/ui/InfoTip.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt } from '$lib/crm/format'
import {
	type ClaimStatus,
	FAILED_STATUSES,
	failureReasons,
	STATUS_INFO
} from '$lib/crm/ownerImportReport'
import { crmQueries } from '$lib/crm/queries'
import { write } from '$lib/crm/write'

/**
 * One owner file's report: the row funnel (rows → dropped → merged → kept → matched / failed),
 * a tile per DLD status, each sheet's column mapping with what it means for its rows, and the
 * kept rows themselves — opening on the failed ones so the manager sees what to fix first.
 */
const imports = createQuery(() => crmQueries.ownerImportDetails())
const id = $derived(Number(page.params.id))
const imp = $derived(imports.data?.find((i) => i.id === id) ?? null)

const STATUS = {
	completed: { label: 'Completed', tone: 'green' },
	processing: { label: 'Processing', tone: 'amber' },
	failed: { label: 'Failed', tone: 'red' }
} as const
const SOURCE = {
	heuristic: 'Built-in column names',
	llm: 'AI header helper',
	heuristic_fallback: 'Built-in names (AI failed)'
}
const FAMILY: Record<string, string> = {
	transaction_party: 'Transaction sheet',
	contact_list: 'Contact list'
}
const statuses = Object.keys(STATUS_INFO) as ClaimStatus[]

let editing = $state(false)
let draft = $state('')
let busy = $state(false)
let confirming = $state(false)

// The rows open on the first failed status that has rows; after that the tiles and the select drive
// it. A processing import has no counts yet, so the choice waits until it has finished. Moving to
// another import also closes any open rename or delete prompt.
let status = $state<ClaimStatus | null>(null)
let chosenFor = $state<number | null>(null)
let shownFor = $state<number | null>(null)
$effect.pre(() => {
	if (!imp) return
	if (shownFor !== imp.id) {
		shownFor = imp.id
		editing = false
		confirming = false
		draft = ''
	}
	if (chosenFor === imp.id || imp.status === 'processing') return
	chosenFor = imp.id
	status = FAILED_STATUSES.find((s) => imp.counts.byStatus[s] > 0) ?? null
})

async function rename(i: OwnerImportDetail) {
	const name = draft.trim()
	if (!name || name === i.name) {
		editing = false
		return
	}
	busy = true
	const r = await write({
		call: () => crm.imports.renameOwners(i.id, name),
		success: `Renamed · ${name}`,
		event: 'import_renamed'
	})
	busy = false
	if (r) editing = false
}

async function remove(i: OwnerImportDetail) {
	busy = true
	const r = await write({
		call: () => crm.imports.removeOwners(i.id),
		success: `Deleted · ${i.name}`,
		event: 'import_deleted'
	})
	busy = false
	if (r) await goto('/crm/owners/imports')
}

const pct = (n: number, of: number) => (of ? `${(n / of) * 100}%` : '0%')
const share = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : '—')
</script>

<svelte:head><title>{imp ? `${imp.name} · ` : ''}Owner imports · CRM Beta</title></svelte:head>

<PageHeader title={imp?.name ?? 'Import report'} facts={imp ? `${imp.file} · ${imp.at}` : ''}>
	{#snippet right()}
		<a class="btn ghost" href="/crm/owners/imports"><ArrowLeft size={15} /><span>All imports</span></a>
	{/snippet}
</PageHeader>

<QueryView query={imports} rows={8}>
	{#snippet children()}
		{#if !imp}
			<div class="notice" role="status">
				This import isn't there any more. <a href="/crm/owners/imports">Back to all imports</a>
			</div>
		{:else}
			{@const c = imp.counts}
			<!-- 1. Header -->
			<section class="card head">
				{#if editing}
					<form
						class="edit"
						onsubmit={(e) => {
							e.preventDefault()
							rename(imp)
						}}
					>
						<input aria-label="Import name" maxlength="200" bind:value={draft} disabled={busy} />
						<button type="submit" class="btn sm" disabled={busy || !draft.trim()}>Save</button>
						<button type="button" class="btn ghost sm" onclick={() => (editing = false)}>Cancel</button>
					</form>
				{:else}
					<div class="title">
						<h2>{imp.name}</h2>
						<Chip tone={STATUS[imp.status].tone}>{STATUS[imp.status].label}</Chip>
					</div>
					<div class="acts">
						{#if confirming}
							<span class="small">Delete this import, its saved list and its rows?</span>
							<button type="button" class="btn danger sm" disabled={busy} onclick={() => remove(imp)}>
								{busy ? 'Deleting…' : 'Delete'}
							</button>
							<button type="button" class="btn ghost sm" onclick={() => (confirming = false)}>Cancel</button>
						{:else}
							<button
								type="button"
								class="btn ghost sm"
								onclick={() => {
									draft = imp.name
									editing = true
								}}>Rename</button
							>
							<button type="button" class="btn ghost sm" onclick={() => (confirming = true)}>Delete</button>
						{/if}
					</div>
				{/if}
			</section>

			{#if imp.status === 'failed'}
				<div class="notice" role="alert">This import failed (import #{imp.id}). Fix the file and upload it again.</div>
			{:else if imp.status === 'processing'}
				<div class="notice" role="status">This file is still being imported. Counts appear when it finishes.</div>
			{/if}

			<!-- 2. Row funnel -->
			<section class="sec">
				<h3>What happened to the rows</h3>
				<div class="bar" aria-hidden="true">
					<span class="seg matched" style:width={pct(c.matched, c.rows)}></span>
					<span class="seg failed" style:width={pct(c.failed, c.rows)}></span>
					<span class="seg merged" style:width={pct(c.merged, c.rows)}></span>
					<span class="seg dropped" style:width={pct(c.dropped, c.rows)}></span>
				</div>
				<div class="grid-4 kpis">
					<div class="kpi"><span class="lbl">Rows in file</span><span class="v">{fmt(c.rows)}</span></div>
					<div class="kpi">
						<span class="lbl"><i class="dot dropped"></i>Dropped</span><span class="v">{fmt(c.dropped)}</span>
						<span class="n">No name, not Buyer/Seller, or mortgage/gift</span>
					</div>
					<div class="kpi">
						<span class="lbl"><i class="dot merged"></i>Duplicates merged</span><span class="v">{fmt(c.merged)}</span>
					</div>
					<div class="kpi">
						<span class="lbl">Owners kept</span><span class="v">{fmt(c.kept)}</span>
						<span class="n">{fmt(c.readyToContact)} ready to contact · {fmt(c.rentalLeads)} rental leads</span>
					</div>
					<div class="kpi green">
						<span class="lbl"><i class="dot matched"></i>Matched to DLD</span><span class="v">{fmt(c.matched)}</span>
						<span class="n">{c.matchRate === null ? '—' : `${Math.round(c.matchRate * 100)}%`} of kept</span>
					</div>
					<div class="kpi red">
						<span class="lbl">
							<i class="dot failed"></i>Failed to match
							{#if c.failed}
								<InfoTip label="Why {fmt(c.failed)} rows failed to match" align="left">
									<b>Why {fmt(c.failed)} rows failed to match DLD</b>
									<ul class="why">
										{#each failureReasons(c) as r (r.status)}
											<li>
												<b>{r.label} · {fmt(r.count)}</b>
												<span>{r.meaning}.</span>
												<span class="fix">Fix: {r.fix}</span>
											</li>
										{/each}
									</ul>
								</InfoTip>
							{/if}
						</span>
						<span class="v">{fmt(c.failed)}</span>
						<span class="n">{share(c.failed, c.kept)} of kept</span>
					</div>
				</div>
			</section>

			<!-- 3. Status breakdown -->
			<section class="sec">
				<h3>By DLD status</h3>
				<div class="grid-4 kpis">
					{#each statuses as s (s)}
						<button
							type="button"
							class={['kpi', status === s && 'on']}
							aria-pressed={status === s}
							disabled={imp.listId === null}
							onclick={() => (status = status === s ? null : s)}
						>
							<span class="lbl"><Chip tone={STATUS_INFO[s].tone}>{STATUS_INFO[s].label}</Chip></span>
							<span class="v sm">{fmt(c.byStatus[s])} <small>{share(c.byStatus[s], c.kept)}</small></span>
							<span class="n">{STATUS_INFO[s].meaning}</span>
						</button>
					{/each}
				</div>
			</section>

			<!-- 4. Sheets and mapping -->
			<section class="sec">
				<h3>Sheets and column mapping</h3>
				{#each imp.sheets as s, i (i)}
					<div class="card sheet">
						<div class="sh">
							<b>{s.name}</b>
							<span class="small muted">
								{fmt(s.rows)} rows · {FAMILY[s.family] ?? s.family} · {SOURCE[s.source] ?? s.source}
								{s.source === 'llm' ? ` · ${Math.round(s.confidence * 100)}% sure` : ''}
							</span>
						</div>
						{#each s.checks as k (k.code)}
							<div class={['check', k.level]} role={k.level === 'error' ? 'alert' : undefined}>
								{k.level === 'error' ? '⚠' : 'ⓘ'}
								{k.text}
							</div>
						{/each}
						<dl class="fields">
							{#each s.fields as f (f.field)}
								<dt>{f.field}</dt>
								<dd>{f.column}</dd>
							{/each}
						</dl>
						{#if s.warnings.length}
							<ul class="small muted warns">
								{#each s.warnings as w, j (j)}<li>{w}</li>{/each}
							</ul>
						{/if}
					</div>
				{:else}
					<p class="small muted">No sheet details were stored for this import.</p>
				{/each}
			</section>

			<!-- 5. Owner rows -->
			<section class="sec">
				<h3>Owner rows</h3>
				{#if imp.listId === null}
					<p class="small muted">No rows were saved for this import.</p>
				{:else}
					{#key imp.listId}
						<ImportRows listId={imp.listId} bind:status />
					{/key}
				{/if}
			</section>
		{/if}
	{/snippet}
</QueryView>

<style>
	.sec + .sec,
	.head + .sec,
	.notice + .sec {
		margin-top: 1.5rem;
	}
	.head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		flex-wrap: wrap;
		gap: 0.75rem;
		padding: 0.9rem 1rem;
		margin-bottom: 1rem;
	}
	.title {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.title h2 {
		margin: 0;
		font-size: 18px;
	}
	.acts,
	.edit {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.edit {
		flex: 1;
	}
	.edit input {
		flex: 1;
		min-width: 12rem;
	}
	.bar {
		display: flex;
		height: 12px;
		border-radius: 6px;
		overflow: hidden;
		background: var(--card-2);
		margin-bottom: 0.75rem;
	}
	.seg.matched,
	.dot.matched {
		background: var(--green);
	}
	.seg.failed,
	.dot.failed {
		background: var(--red);
	}
	.seg.merged,
	.dot.merged {
		background: var(--text2);
	}
	.seg.dropped,
	.dot.dropped {
		background: var(--amber);
	}
	.dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		margin-right: 6px;
	}
	.kpi.on {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px var(--accent);
	}
	.kpi small {
		font-size: 12.5px;
		font-weight: 400;
		color: var(--text2);
	}
	.sheet {
		padding: 0.9rem 1rem;
		margin-bottom: 0.75rem;
		display: grid;
		gap: 0.5rem;
	}
	.sh {
		display: flex;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 0.6rem;
	}
	.check {
		font-size: 13px;
		padding: 0.4rem 0.6rem;
		border-radius: 8px;
	}
	.check.error {
		background: var(--red-bg);
		color: var(--red);
	}
	.check.warning {
		background: var(--amber-bg);
		color: var(--amber);
	}
	.fields {
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.2rem 1rem;
		margin: 0;
		font-size: 13px;
	}
	.fields dt {
		color: var(--text2);
		font-family: var(--mono, ui-monospace, monospace);
		font-size: 12px;
	}
	.fields dd {
		margin: 0;
	}
	.warns {
		margin: 0;
		padding-left: 1.1rem;
	}
	.why {
		margin: 0;
		padding-left: 1.1rem;
		display: grid;
		gap: 0.55rem;
	}
	.why li {
		display: grid;
		gap: 0.1rem;
	}
	.why .fix {
		color: var(--text2);
		font-size: 12px;
	}
</style>
