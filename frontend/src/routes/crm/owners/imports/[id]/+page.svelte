<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import Send from 'lucide-svelte/icons/send'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { crm } from '$lib/crm/api'
import type { OwnerImportDetail } from '$lib/crm/api/types'
import DroppedRows from '$lib/crm/components/imports/DroppedRows.svelte'
import ImportRows from '$lib/crm/components/imports/ImportRows.svelte'
import PropertyRows from '$lib/crm/components/imports/PropertyRows.svelte'
import OwnerImportSummary from '$lib/crm/components/owners/OwnerImportSummary.svelte'
import SourceAuditSummary from '$lib/crm/components/owners/SourceAuditSummary.svelte'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import InfoTip from '$lib/crm/components/ui/InfoTip.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import { fmt } from '$lib/crm/format'
import {
	importIsActive,
	importProgressNotice,
	IMPORT_STATUS as STATUS
} from '$lib/crm/importStatus'
import {
	type ClaimStatus,
	columnsRead,
	DROP_REASON_INFO,
	type DropReason,
	MATCH_FILTERS,
	type MatchBucketKey,
	type MatchFilterId,
	type OwnerMatchView,
	STATUS_HELP,
	STATUS_INFO
} from '$lib/crm/ownerImportReport'
import { crmQueries } from '$lib/crm/queries'
import { panel } from '$lib/crm/stores/panel.svelte'
import { write } from '$lib/crm/write'

/**
 * One owner file's report. Top to bottom: the results block (units identified and mapped, rows to
 * review by reason, sales matched, rows left out; all from the matcher's summary), the kept rows
 * with the sale each was tied to and why, the fields read from the file, and one collapsed
 * "Processing details" holding everything recorded at import time.
 */
const imports = createQuery(() => crmQueries.ownerImportDetails())
/** Managers issue a finished sheet's owners to agents as outbound leads. */
const assignScope = createQuery(() => crmQueries.assignmentScope())
const canIssue = $derived(assignScope.data?.capabilities.can_assign ?? false)
const id = $derived(Number(page.params.id))
const imp = $derived(imports.data?.find((i) => i.id === id) ?? null)

const statuses = Object.keys(STATUS_INFO) as ClaimStatus[]

let editing = $state(false)
let draft = $state('')
let busy = $state(false)
let confirming = $state(false)

// The owner rows open on "All"; the result buckets and the colour chips narrow them. Moving to
// another import resets the filter and closes any open rename or delete prompt.
let filter = $state<MatchFilterId>('all')
// The Dropped card opens the rows the import did not keep, with the reason for each.
let showDropped = $state(false)
// The Properties card opens the import's distinct units, each with its buyer/seller rows.
let showProperties = $state(false)
let shownFor = $state<number | null>(null)
$effect.pre(() => {
	if (!imp || shownFor === imp.id) return
	shownFor = imp.id
	filter = 'all'
	showDropped = false
	showProperties = false
	editing = false
	confirming = false
	draft = ''
})

async function rename(i: OwnerImportDetail) {
	const name = draft.trim()
	if (!name || name === i.name) {
		editing = false
		return
	}
	busy = true
	const r = await write({
		domain: 'imports',
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
		domain: 'imports',
		call: () => crm.imports.removeOwners(i.id),
		success: `Deleted · ${i.name}`,
		event: 'import_deleted'
	})
	busy = false
	if (r) await goto('/crm/owners/imports')
}

// "120 No name · 410 Not Buyer/Seller …", largest first; empty for imports made before the log.
const droppedBreakdown = (byReason: Partial<Record<DropReason, number>>) =>
	(Object.entries(byReason) as [DropReason, number][])
		.filter(([, n]) => n > 0)
		.sort((a, b) => b[1] - a[1])
		.map(([r, n]) => `${fmt(n)} ${DROP_REASON_INFO[r]?.label ?? r}`)
		.join(' · ')

const pct = (n: number, of: number) => (of ? `${(n / of) * 100}%` : '0%')

/** A result bucket narrows the rows to its colour; pressing it again shows all rows. */
function pick(key: MatchBucketKey) {
	filter = filter === key ? 'all' : key
	document.getElementById('source-rows')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
}
const filterLabel = (id: MatchFilterId) => MATCH_FILTERS.find((f) => f.id === id)?.label

/** The header's facts: file, rows, import date and number. */
const facts = (i: OwnerImportDetail) =>
	[
		i.file,
		i.status === 'completed' ? `${fmt(i.counts.rows)} rows` : STATUS[i.status].label,
		`${i.status === 'completed' ? 'imported' : 'uploaded'} ${i.at}`,
		`import #${i.id}`
	].join(' · ')
const count = (n: number, one: string, many: string) => `${fmt(n)} ${n === 1 ? one : many}`

/** Rows the match leaves out: brokers and lenders are not owners; rows with no unit cannot be placed. */
function leftOut(m: OwnerMatchView): string {
	const parties = [
		m.brokerRows ? count(m.brokerRows, 'broker', 'brokers') : '',
		m.lenderRows ? count(m.lenderRows, 'lender', 'lenders') : ''
	].filter(Boolean)
	return [
		parties.length ? `${parties.join(' and ')} (not owners)` : '',
		m.rowsWithoutUnit ? `${count(m.rowsWithoutUnit, 'row', 'rows')} without a unit` : ''
	]
		.filter(Boolean)
		.join(' · ')
}
const share = (n: number, of: number) => (of ? `${Math.round((n / of) * 100)}%` : '—')
</script>
<svelte:head><title>{imp ? `${imp.name} · ` : ''}Owner imports · CRM</title></svelte:head>

<PageHeader title={imp?.name ?? 'Import report'} facts={imp ? facts(imp) : ''}>
	{#snippet right()}
		<a class="btn ghost" href="/crm/owners/imports"><ArrowLeft size={15} /><span>All imports</span></a>
		{#if imp && imp.status === 'completed' && imp.listId !== null && canIssue}
			{@const listId = imp.listId}
			<button
				type="button"
				class="btn"
				onclick={() => panel.open({ kind: 'issue-owners', listId, name: imp.name })}
			>
				<Send size={15} /><span>Issue as outbound leads</span>
			</button>
		{/if}
		{#if imp}
			<button
				type="button"
				class="btn ghost"
				onclick={() => {
					confirming = false
					draft = imp.name
					editing = true
				}}>Rename</button
			>
			<button
				type="button"
				class="btn ghost"
				onclick={() => {
					editing = false
					confirming = true
				}}>Delete</button
			>
		{/if}
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
			{@const m = c.ownerMatch}
			<!-- 1. Rename or delete, opened from the header -->
			{#if editing}
				<form
					class="card bar-form"
					onsubmit={(e) => {
						e.preventDefault()
						rename(imp)
					}}
				>
					<input aria-label="Import name" maxlength="200" bind:value={draft} disabled={busy} />
					<button type="submit" class="btn sm" disabled={busy || !draft.trim()}>Save</button>
					<button type="button" class="btn ghost sm" onclick={() => (editing = false)}>Cancel</button>
				</form>
			{:else if confirming}
				<div class="card bar-form" role="alert">
					<span class="small">Delete this import, its saved list and its rows? Owner notes stay.</span>
					<button type="button" class="btn danger sm" disabled={busy} onclick={() => remove(imp)}>
						{busy ? 'Deleting…' : 'Delete'}
					</button>
					<button type="button" class="btn ghost sm" onclick={() => (confirming = false)}>Cancel</button>
				</div>
			{/if}

			{#if imp.status === 'failed'}
				<div class="notice" role="alert">This import failed (import #{imp.id}). Fix the file and upload it again.</div>
			{:else if importIsActive(imp.status)}
				<div class="notice" role="status">{importProgressNotice(imp.status)}</div>
			{/if}

			<!-- 2. Match result -->
			{#if imp.status === 'completed'}
				<section class="card match" aria-labelledby="match-h">
					<div class="ch">
						<h2 id="match-h">Match results</h2>
					</div>
					{#if !m}
						<div class="cb">
							<p class="pending"><Chip tone="amber">Re-match pending</Chip></p>
							<p class="small muted">Unit counts appear once this file is re-matched.</p>
						</div>
					{:else}
						<div class="cb">
							<div class="stats">
								<div class="stat">
									<span class="sl">Units identified <InfoTip label="What a unit is"><span>A building or project plus a unit number.</span></InfoTip></span>
									<span class="big">{fmt(m.total)}</span>
								</div>
								<div class="stat">
									<span class="sl">Units mapped</span>
									<span class="big ok">{fmt(m.headline.units)}</span>
									<span class="ss">{m.headline.percent}% coverage</span>
								</div>
								<button type="button" class="stat act" aria-pressed={filter === 'review'} aria-controls="source-rows" onclick={() => pick('review')}>
									<span class="sl">Rows to review</span>
									<span class="big warn">{fmt(m.review.rows)}</span>
								</button>
								<div class="stat">
									<span class="sl">Sales matched</span>
									<span class="big">{m.sales ? fmt(m.sales.total) : '—'}</span>
									{#if m.sales}<span class="ss">{fmt(m.sales.withUnit)} with unit details · {fmt(m.sales.withoutUnit)} without a unit number</span>{/if}
								</div>
							</div>
							{#if m.review.reasons.length}
								<h3 class="mini">Rows to review</h3>
								<ul class="reasons" aria-label="Rows to review by reason">
									{#each m.review.reasons as r (r.key)}
										<li title={r.meaning}><span>{r.label}</span><b>{fmt(r.count)}</b></li>
									{/each}
								</ul>
							{/if}
							<h3 class="mini">Units by result</h3>
							<div class="stack" role="img" aria-label={m.buckets.map((b) => `${fmt(b.units)} ${b.label}`).join(', ')}>
								{#each m.buckets as b (b.key)}
									<span class={['seg', b.tone]} style:width={pct(b.units, m.total)}></span>
								{/each}
							</div>
							<ul class="buckets">
								{#each m.buckets as b (b.key)}
									<li class={['bk', b.tone]}>
										<button
											type="button"
											class="bkb"
											aria-pressed={filter === b.key}
											aria-controls="source-rows"
											onclick={() => pick(b.key)}
										>
											<span class="bl"><i class={['dot', b.tone]}></i>{b.label}</span>
											<span class="bn">{fmt(b.units)} <small>{b.percent}%</small></span>
										</button>
										<span class="bk-tip">
											<InfoTip label="What “{b.label}” means">
												<b>{b.label}</b>
												<span>{b.meaning}</span>
											</InfoTip>
										</span>
									</li>
								{/each}
							</ul>
							{#if leftOut(m)}
								<p class="small muted aside">Left out: {leftOut(m)}</p>
							{/if}
						</div>
					{/if}
				</section>
			{/if}

			<!-- 3. Source rows -->
			<section class="sec rows" id="source-rows">
				<h3>Source rows{#if m && filter !== 'all'}<span class="hint">{filterLabel(filter)} only</span>{/if}</h3>
				{#if imp.listId === null}
					<p class="small muted">No rows were saved for this import.</p>
				{:else}
					{#key imp.listId}
						<ImportRows listId={imp.listId} bind:filter matched={m !== null} />
					{/key}
				{/if}
			</section>

			<!-- 4. Columns read from the file -->
			{#if imp.sheets.length}
				<section class="sec cols" aria-labelledby="cols-h">
					<h3 id="cols-h">Columns read</h3>
					<div class="sheets">
						{#each imp.sheets as sheet (sheet.name)}
							{@const r = columnsRead(sheet)}
							<div class="card sheet">
								<div class="ch">
									<h2>{r.name}<span class="ct">{fmt(sheet.rows)} rows</span></h2>
									{#if r.auto}<Chip tone="blue" title={r.sourceNote}>Auto-mapped</Chip>{/if}
								</div>
								<div class="cb">
									{#each r.checks as check (check.code)}
										<p class={['small', 'check', check.level]}>{check.text}</p>
									{/each}
									{#each r.warnings as w (w)}<p class="small warnline">{w}</p>{/each}
									<dl class="map">
										{#each r.fields as f (f.field)}
											<div><dt>{f.field}</dt><dd class={[!f.found && 'missing']}>{f.found ? 'Found' : 'Not found'}</dd></div>
										{/each}
									</dl>
									{#if r.unused}<p class="small muted">{count(r.unused, 'column', 'columns')} not used</p>{/if}
								</div>
							</div>
						{/each}
					</div>
				</section>
			{/if}

			<!-- 5. Processing details -->
			<details class="snapshot">
				<summary>Processing details</summary>
				{#if imp.status === 'completed'}
					<p class="small muted row-accounting">{fmt(c.rows)} source rows · {fmt(c.kept)} kept · {fmt(c.merged)} merged · {fmt(c.dropped)} dropped.</p>
					{#if c.rows !== c.kept + c.merged + c.dropped}<p class="notice" role="status">The row totals do not add up to the source rows.</p>{/if}
				{/if}

				{#if imp.source_audit}
				<SourceAuditSummary summary={imp.source_audit} />
			{/if}

				<OwnerImportSummary importId={imp.id} listId={imp.listId} processing={importIsActive(imp.status)} />

				<button type="button" class="btn ghost sm" aria-expanded={showProperties} aria-controls="property-rows" onclick={() => (showProperties = !showProperties)}>{showProperties ? 'Hide properties' : 'Show properties'}</button>

				{#if showProperties}
				<section class="sec" id="property-rows">
					<h3>Properties</h3>
					<PropertyRows importId={imp.id} />
				</section>
			{/if}


			<section class="sec">
				<h3>What happened to the rows</h3>
				<div class="bar" aria-hidden="true">
					<span class="seg matched" style:width={pct(c.kept, c.rows)}></span>
					<span class="seg merged" style:width={pct(c.merged, c.rows)}></span>
					<span class="seg dropped" style:width={pct(c.dropped, c.rows)}></span>
				</div>
				<div class="grid-4 kpis">
					
					<button
						type="button"
						class={['kpi', showDropped && 'on']}
						aria-pressed={showDropped}
						aria-controls="dropped-rows"
						disabled={!c.dropped}
						onclick={() => (showDropped = !showDropped)}
					>
						<span class="lbl"><i class="dot dropped"></i>Dropped</span><span class="v">{fmt(c.dropped)}</span>
						<span class="n">{droppedBreakdown(c.droppedByReason) || 'No rejected source rows'}</span>
						{#if c.dropped}<span class="n link">{showDropped ? 'Hide rows' : 'Show rows'}</span>{/if}
					</button>
					<div class="kpi">
						<span class="lbl"><i class="dot merged"></i>Duplicates merged</span><span class="v">{fmt(c.merged)}</span>
					</div>
					
					
					<div class="kpi">
						<span class="lbl">Rows linked to a property</span><span class="v">{c.matched === null ? '—' : fmt(c.matched)}</span>
						<span class="n">{c.matchRate === null ? '—' : `${Math.round(c.matchRate * 100)}%`} of {fmt(c.kept)} kept rows · {c.sourceMatchRate === null ? '—' : `${Math.round(c.sourceMatchRate * 100)}%`} of {fmt(c.rows)} source rows</span>
						{#if c.salesHistoryRows !== null}
							<span class="n">{fmt(c.salesHistoryRows)} with sales history · {fmt(c.plotOnlyRows ?? 0)} plot only</span>
						{/if}
					</div>
					<div class="kpi">
						<span class="lbl">Current owners</span><span class="v">{fmt(c.byStatus.verified_current_owner)}</span>
						<span class="n">{share(c.byStatus.verified_current_owner, c.kept)} of kept rows</span>
					</div>
					<div class="kpi">
						<span class="lbl">Rows with phone or email</span><span class="v">{fmt(c.validContacts)}</span>
						<span class="n">{share(c.validContacts, c.kept)} of kept rows</span>
					</div>
					<div class="kpi">
						<span class="lbl">Contactable candidates</span><span class="v">{fmt(c.readyToContact)}</span>
						<span class="n">{share(c.readyToContact, c.kept)} of kept rows · {fmt(c.rentalLeads)} rental leads</span>
					</div>
				</div>
				{#if c.sourceProperties}
					{@const source = c.sourceProperties}
					<h3>Identifiers in the file</h3>
					<div class="grid-4 kpis">
						<div class="kpi">
							<span class="lbl">Source property references</span><span class="v">{fmt(source.source_property_references ?? 0)}</span>
							
						</div>
						<div class="kpi">
							<span class="lbl">Property numbers without a unit</span><span class="v">{fmt(source.distinct_property_numbers_without_unit ?? 0)}</span>
							
						</div>
						<div class="kpi">
							<span class="lbl">Distinct unit numbers</span><span class="v">{fmt(source.distinct_unit_numbers ?? 0)}</span>
							<span class="n">{fmt(source.location_scoped_units ?? 0)} building/project + unit combinations</span>
						</div>
						<div class="kpi">
							<span class="lbl">Building numbers without a unit</span><span class="v">{fmt(source.distinct_building_numbers_without_unit ?? 0)}</span>
							
						</div>
						<div class="kpi">
							<span class="lbl">Combined identifiers</span><span class="v">{fmt(source.distinct_identifiers ?? 0)}</span>
							
						</div>
						<div class="kpi">
							<span class="lbl">Rows missing both identifiers</span><span class="v">{fmt(source.rows_without_identifiers ?? 0)}</span>
							
						</div>
					</div>
				{/if}
			</section>

			
			<section class="sec">
				<h3>Ownership by row</h3>
				<div class="grid-4 kpis">
					{#each statuses as s (s)}
						<!-- Historical classifications are separate from the current row filter. -->
						<div class="stile">
							<div class="kpi">
								<span class="lbl"><Chip tone={STATUS_INFO[s].tone}>{STATUS_INFO[s].label}</Chip></span>
								<span class="v sm">{fmt(c.byStatus[s])} <small>{share(c.byStatus[s], c.kept)}</small></span>
								<span class="n">{STATUS_INFO[s].meaning}</span>
							</div>
							<span class="stip">
								<InfoTip label="What “{STATUS_INFO[s].label}” means">
									<b>{STATUS_INFO[s].label}</b>
									<span>{STATUS_HELP[s].how}</span>
									<span class="todo">{STATUS_HELP[s].todo}</span>
								</InfoTip>
							</span>
						</div>
					{/each}
				</div>
			</section>

			

				{#if showDropped}
					<section class="sec" id="dropped-rows">
						<h3>Dropped rows</h3>
						<DroppedRows importId={imp.id} />
					</section>
				{/if}
			</details>
		{/if}
	{/snippet}
</QueryView>

<style>
	.match {
		margin-bottom: 1.25rem;
	}
	.stats {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 0.5rem;
		margin-bottom: 1rem;
	}
	.stat {
		display: grid;
		align-content: start;
		gap: 0.2rem;
		padding: 0.7rem 0.8rem;
		border: 1px solid var(--sep);
		border-radius: 10px;
		background: var(--card);
		color: var(--text);
		text-align: left;
		font: inherit;
	}
	.stat.act {
		cursor: pointer;
	}
	.stat.act:hover {
		background: var(--hover);
	}
	.stat.act[aria-pressed='true'] {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px var(--accent);
	}
	.stat .sl {
		font-size: 12px;
		font-weight: 600;
		color: var(--text2);
	}
	.stat .big {
		font-size: 30px;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.1;
		font-variant-numeric: tabular-nums;
	}
	.stat .big.ok {
		color: var(--green);
	}
	.stat .big.warn {
		color: var(--amber);
	}
	.stat .ss {
		font-size: 12.5px;
		color: var(--text2);
	}
	.mini {
		margin: 0 0 0.4rem;
		font-size: 12px;
		font-weight: 600;
		color: var(--text2);
	}
	.reasons {
		list-style: none;
		margin: 0 0 1rem;
		padding: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}
	.reasons li {
		display: inline-flex;
		gap: 0.5rem;
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		background: var(--amber-bg);
		font-size: 12.5px;
	}
	.reasons b {
		font-variant-numeric: tabular-nums;
	}
	.stack {
		display: flex;
		height: 14px;
		border-radius: 7px;
		overflow: hidden;
		background: var(--card-2);
		margin-bottom: 0.8rem;
	}
	.stack .seg.green,
	.dot.green {
		background: var(--green);
	}
	.stack .seg.amber,
	.dot.amber {
		background: var(--amber);
	}
	.stack .seg.blue,
	.dot.blue {
		background: var(--blue);
	}
	.stack .seg.red,
	.dot.red {
		background: var(--red);
	}
	.stack .seg.neutral,
	.dot.neutral {
		background: var(--muted);
	}
	.stack .seg + .seg {
		box-shadow: inset 2px 0 0 var(--card);
	}
	.buckets {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 0.5rem;
	}
	.bk {
		position: relative;
	}
	.bkb {
		display: grid;
		gap: 0.2rem;
		width: 100%;
		text-align: left;
		padding: 0.6rem 2rem 0.6rem 0.7rem;
		border: 1px solid var(--sep);
		border-radius: 10px;
		background: var(--card);
		color: var(--text);
		cursor: pointer;
	}
	.bkb:hover {
		background: var(--hover);
	}
	.bkb[aria-pressed='true'] {
		border-color: var(--accent);
		box-shadow: 0 0 0 1px var(--accent);
	}
	.bl {
		font-size: 12px;
		font-weight: 600;
		color: var(--text2);
	}
	.bn {
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.bn small {
		font-size: 12.5px;
		font-weight: 400;
		color: var(--text2);
	}
	.bk-tip {
		position: absolute;
		top: 8px;
		right: 8px;
	}
	.aside {
		margin: 0.7rem 0 0;
	}
	.pending {
		margin: 0 0 0.4rem;
	}
	.rows {
		margin-bottom: 1.5rem;
	}
	.rows h3 .hint {
		font-weight: 400;
		color: var(--text2);
	}
	.cols {
		margin-bottom: 1.5rem;
	}
	.sheets {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(min(100%, 22rem), 1fr));
		gap: 0.75rem;
	}
	.sheet .cb {
		display: grid;
		gap: 0.45rem;
	}
	.sheet p {
		margin: 0;
	}
	.check.error {
		color: var(--red);
	}
	.check.warning,
	.warnline {
		color: var(--amber);
	}
	.map {
		margin: 0;
		display: grid;
	}
	.map > div {
		display: flex;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.3rem 0;
		border-top: 1px solid var(--sep);
		font-size: 12.5px;
	}
	.map dt {
		color: var(--text2);
	}
	.map dd {
		margin: 0;
		font-weight: 600;
		text-align: right;
	}
	.map dd.missing {
		font-weight: 400;
		color: var(--text2);
	}
	@media (max-width: 900px) {
		.stats,
		.buckets {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}
	.snapshot { margin-top: 1.5rem; }
	.row-accounting { font-variant-numeric: tabular-nums; }
	.kpis { display: block; }
	.kpis .kpi {
		display: grid;
		grid-template-columns: minmax(10rem, 1fr) auto;
		gap: 0.25rem 1rem;
		padding: 0.65rem 0;
		border: 0;
		border-bottom: 1px solid var(--sep);
		border-radius: 0;
		background: transparent;
		box-shadow: none;
	}
	.kpis .kpi .v, .kpis .kpi .v.sm { font-size: 14px; }
	.kpis .kpi .n { grid-column: 1 / -1; }

	.snapshot > summary { cursor: pointer; font-weight: 600; }
	.snapshot > :not(summary) { margin-top: 1rem; }
	.sec + .sec {
		margin-top: 1.5rem;
	}
	.bar-form {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.4rem;
		padding: 0.75rem 1rem;
		margin-bottom: 1rem;
	}
	.bar-form input {
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
	.kpi .link {
		color: var(--accent);
	}
	.kpi small {
		font-size: 12.5px;
		font-weight: 400;
		color: var(--text2);
	}
	.stile {
		position: relative;
		display: grid;
	}
	.stile > .kpi {
		width: 100%;
	}
	.stip {
		position: absolute;
		top: 10px;
		right: 10px;
	}
	.todo {
		color: var(--text2);
		font-size: 12px;
	}
</style>
