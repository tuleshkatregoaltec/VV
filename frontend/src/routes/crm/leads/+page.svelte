<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Search from 'lucide-svelte/icons/search'
import Upload from 'lucide-svelte/icons/upload'
import { crm } from '$lib/crm/api'
import { LEASE_PAGE_SIZE } from '$lib/crm/api/backend'
import type {
	LeadListParams,
	LeadRow,
	LeadStage,
	LeadType,
	LeaseWindow,
	Source
} from '$lib/crm/api/types'
import { canDrop, columnTotal, initials, needLine } from '$lib/crm/board'
import TeamAnalytics from '$lib/crm/components/manager/TeamAnalytics.svelte'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import FilterMenu from '$lib/crm/components/ui/FilterMenu.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import ScoreChip from '$lib/crm/components/ui/ScoreChip.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import StageChip from '$lib/crm/components/ui/StageChip.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import {
	BEDS_OPTIONS,
	BUDGET_OPTIONS,
	GATE_LINE,
	groupOf,
	LEAD_GROUPS,
	LEAD_TYPE_ORDER,
	LEAD_TYPES,
	type LeadGroup,
	PTYPE_OPTIONS,
	SOURCES,
	STAGES,
	stagesFor
} from '$lib/crm/config'
import { fmt } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { openLead, panel } from '$lib/crm/stores/panel.svelte'
import { clearLeadFilters, type LeadTab, ui } from '$lib/crm/stores/ui.svelte'
import { errorText, write } from '$lib/crm/write'

const me = createQuery(() => crmQueries.me())
const scope = createQuery(() => crmQueries.assignmentScope())
/** Managers and administrators also get a per-person view (Agents, 17 Nov 2026). */
const canAssign = $derived(scope.data?.capabilities.can_assign ?? false)
const viewItems = $derived([
	{ id: 'list' as const, label: 'List' },
	{ id: 'board' as const, label: 'Board' },
	...(canAssign ? [{ id: 'agents' as const, label: 'Agents' }] : [])
])
const showAgents = $derived(canAssign && ui.leadView === 'agents')
const feed = createQuery(() => crmQueries.feedSummary())

// Search updates the rows as you type; only the rows re-render, the input keeps focus.
let q = $state(ui.q)
$effect(() => {
	const v = ui.q.trim()
	const t = setTimeout(() => (q = v), 150)
	return () => clearTimeout(t)
})

const tabType = $derived(
	LEAD_TYPE_ORDER.includes(ui.leadTab as LeadType) ? (ui.leadTab as LeadType) : null
)
/** On the board, a type tab picks its own group; otherwise the group switch does. */
const group = $derived<LeadGroup>(tabType ? groupOf(tabType) : ui.leadGroup)

// Lease leads come one server page at a time: leases still running (soonest end first) or ended.
let leaseWindow = $state<LeaseWindow>('upcoming')
let leaseOffset = $state(0)
function pickLeaseWindow(w: LeaseWindow) {
	leaseWindow = w
	leaseOffset = 0
}

const params = $derived<LeadListParams>({
	lead_type: tabType ?? '',
	lost: ui.leadTab === 'lost' ? true : undefined,
	// The board has a Lost column: give it the lost leads the list view keeps under the Lost tab.
	include_lost: ui.leadView === 'board' ? true : undefined,
	source: ui.source,
	stage: ui.stage,
	area: ui.area,
	beds: ui.beds,
	ptype: ui.ptype,
	budget: ui.budget,
	q,
	// Vitevue lease leads from My areas join the agency's own leads here.
	vitevue: true,
	lease_window: leaseWindow,
	lease_offset: leaseOffset
})
const leads = createQuery(() => crmQueries.leads(params))
const leasePage = $derived(leads.data?.lease_page)
const leaseEnd = $derived(
	leasePage ? Math.min(leasePage.offset + leasePage.limit, leasePage.total) : 0
)
const counts = $derived(leads.data?.counts)
const more = $derived((ui.beds ? 1 : 0) + (ui.ptype ? 1 : 0) + (ui.budget ? 1 : 0))
const filtered = $derived(Boolean(ui.q || ui.source || ui.stage || ui.area || more))

const tabs = $derived([
	{ id: 'all' as LeadTab, label: 'All', count: counts?.all },
	...LEAD_TYPE_ORDER.map((t) => ({
		id: t as LeadTab,
		label: LEAD_TYPES[t].plural,
		count: counts?.[t]
	})),
	{ id: 'lost' as LeadTab, label: 'Lost', count: counts?.lost }
])

/** The Stage filter lists the stages of the type on screen (7 Oct). */
const stageOptions = $derived(
	tabType
		? stagesFor(tabType)
		: ui.leadView === 'board'
			? stagesFor(LEAD_GROUPS[group].types[0])
			: STAGES
)
const boardStages = $derived(stagesFor(LEAD_GROUPS[group].types[0]))

function pickGroup(g: LeadGroup) {
	ui.leadGroup = g
	if (tabType && groupOf(tabType) !== g) ui.leadTab = 'all'
	if (ui.stage && !stagesFor(LEAD_GROUPS[g].types[0]).some((s) => s.id === ui.stage)) ui.stage = ''
}

function selectTab(t: LeadTab) {
	ui.leadTab = t
	const type = LEAD_TYPE_ORDER.includes(t as LeadType) ? (t as LeadType) : null
	if (type && ui.stage && !stagesFor(type).some((s) => s.id === ui.stage)) ui.stage = ''
}

/** A Vitevue lease nobody has opened yet (id 0) becomes the agency's shared lead on open. */
async function open(l: LeadRow) {
	if (l.id) return openLead(l.id)
	if (!l.lease) return
	const leaseId = l.lease.id
	const r = await write({
		domain: 'leads',
		call: () => crm.leads.openVitevue(leaseId),
		success: `${l.lease.unit} is now a lead`
	})
	if (r) openLead(r.data.id)
}

/** Board drag and drop: the card being dragged and the column under it. */
let dragging = $state<LeadRow | null>(null)
let over = $state<LeadStage | null>(null)

/**
 * A drop asks for what the stage needs: back to New saves at once (it needs nothing); any other
 * stage opens the lead on that stage's form, and the card moves once the form is saved.
 */
function dropOn(to: LeadStage) {
	const l = dragging
	dragging = null
	over = null
	if (!l || !canDrop(l, to)) return
	if (to === 'new') {
		write({
			call: () => crm.leads.moveStage(l.id, { stage: 'new' }),
			success: `${l.name} → New`,
			event: 'lead_stage_changed'
		})
		return
	}
	openLead(l.id, `stage:${to}`)
}

const rowKey = (l: LeadRow) => (l.id ? String(l.id) : `lease:${l.lease?.id}`)

const typeLine = (l: LeadRow) =>
	[
		`${LEAD_TYPES[l.lead_type].label}${l.off_plan ? ' · off-plan' : ''}`,
		SOURCES[l.source].label === l.source_short ? null : l.source_short,
		l.listing?.label,
		l.received_label
	]
		.filter(Boolean)
		.join(' · ')
</script>

<svelte:head><title>Leads · CRM</title></svelte:head>

{#if leads.data?.limited}<p class="small muted">Showing the first 500 stored leads. Filters and counts apply to loaded rows.</p>{/if}

<PageHeader
	title="Leads"
	facts={leads.data
		? `${leads.data.counts.all} leads · ${leads.data.new_count} new · ${me.data?.name ?? ''}`
		: ''}
>
	{#snippet right()}
		<button type="button" class="btn ghost" onclick={() => panel.open({ kind: 'new-import', leadsOnly: true })}>
			<Upload size={15} /><span>Import leads</span>
		</button>
		<Seg
			label="View"
			items={viewItems}
			value={showAgents ? 'agents' : ui.leadView === 'agents' ? 'list' : ui.leadView}
			onselect={(v) => (ui.leadView = v)}
		/>
	{/snippet}
</PageHeader>
{#if showAgents}
	<TeamAnalytics />
{:else}

<div class="card feedstrip">
	<span class="srcdot" style:--c="var(--l-vv)">
		{feed.data
			? `Lease ends · next ${feed.data.forward_days} days, last ${feed.data.lookback_days} days`
			: 'Lease ends'}
	</span>
	{#if feed.data && !feed.data.areas.length}
		<span class="sep">·</span>
		<span class="muted">No areas selected</span>
	{:else if feed.data}
		<span class="sep">·</span>
		<b>{feed.data.areas.join(', ')}</b>
		<span class="sep">·</span>
		<span><b class="num">{fmt(feed.data.window_total)}</b> units</span>
		<span class="sep">·</span>
		<span><b class="num">{fmt(feed.data.upcoming ?? 0)}</b> upcoming</span>
		<span class="sep">·</span>
		<span><b class="num">{fmt(feed.data.expired ?? 0)}</b> ended</span>
		<span class="sep">·</span>
		<span
			><b class="num">{fmt(feed.data.on_file)}</b> of the first {fmt(feed.data.loaded ?? 0)} upcoming have a known
			owner</span
		>
		<span class="sep">·</span>
		<span><b class="num">{fmt(feed.data.entered_today)}</b> entered the inbox today</span>
	{:else if feed.isError}
		<span class="muted">
			Could not load. <button type="button" class="linkbtn" onclick={() => feed.refetch()}>Retry</button>
		</span>
	{/if}
	<button type="button" class="btn ghost sm" onclick={() => panel.open({ kind: 'areas' })}>My areas</button>
</div>

{#if feed.data && !feed.data.areas.length}
	<div class="card noareas" role="status">
		<b>No areas chosen, so no lease leads are listed.</b>
		<span class="muted">
			Lease leads follow the areas you pick. This is not an empty market: choose your areas to see
			the leases ending in them.
		</span>
		<button type="button" class="btn sm" onclick={() => panel.open({ kind: 'areas' })}>
			Choose your areas
		</button>
	</div>
{/if}

<Tabs label="Lead type" items={tabs} value={ui.leadTab} onselect={selectTab} />

<div class="filters">
	<label class="search">
		<Search size={15} />
		<span class="sr-only">Search leads</span>
		<input placeholder="Name, phone, unit" autocomplete="off" bind:value={ui.q} />
	</label>
	<FilterMenu
		label="Source"
		allLabel="All sources"
		value={ui.source}
		options={Object.entries(SOURCES).map(([id, s]) => ({ id: id as Source, label: s.label }))}
		onselect={(v) => (ui.source = v)}
	/>
	<FilterMenu
		label="Stage"
		allLabel="All stages"
		value={ui.stage}
		options={stageOptions.map((s) => ({ id: s.id as LeadStage, label: s.label }))}
		onselect={(v) => (ui.stage = v)}
	/>
	<FilterMenu
		label="Area"
		allLabel="All areas"
		value={ui.area}
		options={(leads.data?.areas ?? []).map((a) => ({ id: a, label: a }))}
		onselect={(v) => (ui.area = v)}
	/>
	<button
		type="button"
		class={['btn ghost sm fbtn', more && 'on']}
		aria-expanded={ui.leadMore}
		aria-controls="lead-more"
		onclick={() => (ui.leadMore = !ui.leadMore)}
	>
		All filters{more ? ` · ${more}` : ''}
	</button>
	{#if filtered}
		<button type="button" class="btn plain sm" onclick={clearLeadFilters}>Clear</button>
	{/if}
	<span class="count" aria-live="polite">
		{leads.data ? `${leads.data.total} lead${leads.data.total === 1 ? '' : 's'}` : ''}
	</span>
</div>
{#if ui.leadMore}
	<div class="card morefilters" id="lead-more">
		<FilterMenu
			label="Bedrooms"
			allLabel="Any bedrooms"
			value={ui.beds}
			options={BEDS_OPTIONS}
			onselect={(v) => (ui.beds = v)}
		/>
		<FilterMenu
			label="Type"
			allLabel="Any type"
			value={ui.ptype}
			options={PTYPE_OPTIONS}
			onselect={(v) => (ui.ptype = v)}
		/>
		<FilterMenu
			label="Budget"
			allLabel="Any budget"
			value={ui.budget}
			options={BUDGET_OPTIONS}
			onselect={(v) => (ui.budget = v)}
		/>
	</div>
{/if}

{#if ui.leadView === 'board'}
	<div class="boardhead">
		<Seg
			label="Lead group"
			items={(['bt', 'sl'] as LeadGroup[]).map((g) => ({ id: g, label: LEAD_GROUPS[g].label }))}
			value={group}
			onselect={pickGroup}
		/>
	</div>
{/if}

{#if leasePage}
	<div class="leasepager">
		<Seg
			label="Lease leads"
			items={[
				{ id: 'upcoming' as LeaseWindow, label: `Upcoming renewals · ${fmt(leasePage.counts.upcoming)}` },
				{ id: 'expired' as LeaseWindow, label: `Ended · ${fmt(leasePage.counts.expired)}` }
			]}
			value={leaseWindow}
			onselect={pickLeaseWindow}
		/>
		<span class="small muted" aria-live="polite">
			{leasePage.total
				? `Lease leads ${fmt(leasePage.offset + 1)}–${fmt(leaseEnd)} of ${fmt(leasePage.total)}`
				: 'No lease leads in this window'}{leasePage.total > leasePage.limit
				? ' · filters and counts cover this page'
				: ''}
		</span>
		<button
			type="button"
			class="btn ghost sm"
			disabled={leasePage.offset === 0}
			onclick={() => (leaseOffset = Math.max(0, leaseOffset - LEASE_PAGE_SIZE))}>Previous</button
		>
		<button
			type="button"
			class="btn ghost sm"
			disabled={leaseEnd >= leasePage.total}
			onclick={() => (leaseOffset += LEASE_PAGE_SIZE)}>Next</button
		>
	</div>
{/if}

{#if leads.data?.vitevue_unavailable}
	<ErrorLine bar message="Lease leads could not load." onretry={() => leads.refetch()} />
{/if}
{#if leads.isError && leads.data}
	<ErrorLine bar message={errorText(leads.error)} onretry={() => leads.refetch()} />
{/if}

{#if leads.data}
	{@const rows = leads.data.items}
	{#if ui.leadView === 'board'}
		{@const grows = rows.filter((l) => LEAD_GROUPS[group].types.includes(l.lead_type))}
		{#if grows.length}
			<div class="lboard">
				{#each boardStages as s (s.id)}
					{@const cards = grows.filter((l) => l.stage === s.id)}
					{@const total = columnTotal(cards)}
					{@const ok = dragging ? canDrop(dragging, s.id) : false}
					<section
						class={[
							'col',
							dragging && ok && 'drop-ok',
							dragging && !ok && dragging.stage !== s.id && 'drop-no',
							over === s.id && 'drop-over'
						]}
						aria-label="{s.label}, {cards.length} leads{total ? `, ${total}` : ''}"
						ondragover={(e) => {
							if (!dragging || !canDrop(dragging, s.id)) return
							e.preventDefault()
							if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
							over = s.id
						}}
						ondragleave={(e) => {
							if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null) && over === s.id) over = null
						}}
						ondrop={(e) => {
							e.preventDefault()
							dropOn(s.id)
						}}
					>
						<div class="colh"><span>{s.label}</span><span>{cards.length}</span></div>
						{#if total}<div class="colt">{total}</div>{/if}
						{#each cards as l (rowKey(l))}
							{@const need = needLine(l)}
							<button
								type="button"
								class={['bcard', 'cl', 'lcard', dragging === l && 'lifted']}
								style:--c={SOURCES[l.source].color}
								draggable={l.id ? 'true' : 'false'}
								title={l.id ? 'Drag to another stage, or click to open' : undefined}
								onclick={() => open(l)}
								ondragstart={(e) => {
									dragging = l
									if (e.dataTransfer) {
										e.dataTransfer.effectAllowed = 'move'
										e.dataTransfer.setData('text/plain', String(l.id))
									}
								}}
								ondragend={() => {
									dragging = null
									over = null
								}}
							>
								<span class="lc-top">
									<span class="lc-av" aria-hidden="true">{initials(l.name)}</span>
									<span class="lc-who">
										<span class="t lc-name">{l.name}</span>
										<span class="d">{LEAD_TYPES[l.lead_type].label} · {l.source_short || SOURCES[l.source].label}</span>
									</span>
									<ScoreChip score={l.score} />
								</span>
								{#if need}<span class="lc-need">{need}</span>{/if}
								{#if l.next_action}<span class="lc-next">↳ {l.next_action}</span>{/if}
								<span class="d">{l.agent ?? 'Unassigned'} · {l.received_label}</span>
								{#if l.gated}<Chip tone="amber">No prior deal</Chip>{/if}
							</button>
						{:else}
							<span class="none">None</span>
						{/each}
					</section>
				{/each}
			</div>
		{:else}
			<div class="card">
				<Empty
					text={group === 'sl'
						? 'No seller or landlord leads match.'
						: 'No buyer or tenant leads match.'}
				>
					{#if filtered}
						<button type="button" class="btn ghost sm" onclick={clearLeadFilters}>Clear filters</button>
					{/if}
				</Empty>
			</div>
		{/if}
	{:else}
		<div class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Lead</th><th>Details</th><th>On your agency's file</th><th>Score</th><th>Stage</th><th
								>Agent</th
							><th>Next</th>
						</tr>
					</thead>
					<tbody>
						{#each rows as l (rowKey(l))}
							<tr class="row">
								<td class="cl" style:--c={SOURCES[l.source].color}>
									<button type="button" class="rowlink" onclick={() => open(l)}>{l.name}</button>
									<div class="sub">{SOURCES[l.source].label} · {typeLine(l)}</div>
								</td>
								<td data-label="Details">
									<div><div>{l.summary.line}</div><div class="sub">{l.summary.sub}</div></div>
								</td>
								<td class="sub" data-label="On file">{l.known}</td>
								<td data-label="Score"><ScoreChip score={l.score} /></td>
								<td data-label="Stage"><StageChip stage={l.stage} /></td>
								<td data-label="Agent" class="nowrap">
									{#if l.agent}{l.agent}{:else}<Chip tone="amber">Unassigned</Chip>{/if}
								</td>
								<td data-label="Next">
									{#if l.gated}
										<Chip tone="amber">No prior deal</Chip>
										<div class="sub">{GATE_LINE}</div>
									{:else}
										<span class="sub">{l.next_action}</span>
									{/if}
								</td>
							</tr>
						{:else}
							<tr>
								<td colspan="7">
									{#if filtered || ui.leadTab !== 'all'}
										<Empty text="No leads match these filters.">
											<button
												type="button"
												class="btn ghost sm"
												onclick={() => {
													clearLeadFilters()
													ui.leadTab = 'all'
												}}>Clear filters</button
											>
										</Empty>
									{:else}
										<Empty text="No leads yet.">
											<button type="button" class="btn sm" onclick={() => panel.open({ kind: 'new-lead' })}>
												New lead
											</button>
										</Empty>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
{:else if leads.isError}
	<div class="card"><ErrorLine message={errorText(leads.error)} onretry={() => leads.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={6} /></div>
{/if}
{/if}

<style>
	/* ── Leads board ── */
	.colt {
		margin-top: -4px;
		padding: 0 4px 2px;
		font-size: 12px;
		color: var(--text3);
		font-variant-numeric: tabular-nums;
	}
	.col {
		transition:
			opacity 0.12s,
			box-shadow 0.12s,
			background 0.12s;
	}
	.col.drop-ok {
		box-shadow: inset 0 0 0 1px var(--sep);
	}
	.col.drop-over {
		box-shadow: inset 0 0 0 2px var(--accent);
		background: color-mix(in srgb, var(--accent) 8%, var(--sunk));
	}
	.col.drop-no {
		opacity: 0.45;
	}
	.lcard {
		gap: 4px;
		padding: 8px 9px;
		cursor: grab;
	}
	.lcard:active {
		cursor: grabbing;
	}
	.lcard.lifted {
		opacity: 0.4;
	}
	.lc-top {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: start;
		gap: 8px;
	}
	.lc-av {
		width: 26px;
		height: 26px;
		border-radius: 50%;
		display: grid;
		place-items: center;
		font-size: 11px;
		font-weight: 600;
		color: var(--c);
		background: color-mix(in srgb, var(--c) 18%, transparent);
	}
	.lc-who {
		display: flex;
		flex-direction: column;
		gap: 1px;
		min-width: 0;
	}
	.lc-name {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		overflow-wrap: anywhere;
	}
	.lc-need {
		font-size: 12px;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lc-next {
		font-size: 12px;
		color: var(--text2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lease {
		display: grid;
		grid-template-columns: auto auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 12px 24px;
		padding: 12px 16px;
	}
	.lease-head {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.lease-title {
		font-size: 14px;
		font-weight: 600;
		color: var(--text);
	}
	.lease-window {
		font-size: 12px;
		color: var(--text2);
		padding-left: 13px;
	}
	.lease-stats {
		display: flex;
		gap: 24px;
		margin: 0;
		padding-left: 24px;
		border-left: 1px solid var(--sep);
	}
	.lease-stats div {
		display: flex;
		flex-direction: column-reverse;
		gap: 1px;
	}
	.lease-stats dt {
		font-size: 12px;
		color: var(--text2);
	}
	.lease-stats dd {
		margin: 0;
		font-size: 17px;
		font-weight: 600;
		color: var(--text);
		font-variant-numeric: tabular-nums;
	}
	.lease-areas {
		margin: 0;
		min-width: 0;
		font-size: 13px;
		color: var(--text2);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.lease-count {
		font-weight: 600;
		color: var(--text);
		margin-right: 6px;
	}
	@media (max-width: 900px) {
		.lease {
			grid-template-columns: minmax(0, 1fr) auto;
		}
		.lease-stats {
			grid-column: 1 / -1;
			grid-row: 2;
			padding-left: 0;
			border-left: 0;
		}
		.lease-areas {
			grid-column: 1 / -1;
			white-space: normal;
		}
		.lease-btn {
			grid-row: 1;
			grid-column: 2;
		}
	}
</style>
