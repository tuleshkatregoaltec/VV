<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Search from 'lucide-svelte/icons/search'
import type { OwnerListParams, OwnerSource, OwnerTab, PropertyKind } from '$lib/crm/api/types'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import FilterMenu from '$lib/crm/components/ui/FilterMenu.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import QueryView from '$lib/crm/components/ui/QueryView.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { BEDS_OPTIONS, OWNER_SOURCES, PTYPE_OPTIONS, stageOf } from '$lib/crm/config'
import { fmt } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { openOwner, panel } from '$lib/crm/stores/panel.svelte'
import { clearOwnerFilters, ui } from '$lib/crm/stores/ui.svelte'
import { errorText } from '$lib/crm/write'

// Search updates the rows as you type; the input keeps focus.
let q = $state(ui.ownerQ)
$effect(() => {
	const v = ui.ownerQ.trim()
	const t = setTimeout(() => (q = v), 150)
	return () => clearTimeout(t)
})

const params = $derived<OwnerListParams>({
	tab: ui.ownerTab,
	q,
	source: ui.ownerSource,
	area: ui.ownerArea,
	beds: ui.ownerBeds,
	ptype: ui.ownerPtype
})
const owners = createQuery(() => crmQueries.owners(params))
const imports = createQuery(() => crmQueries.imports())
const o = $derived(owners.data)
const filtered = $derived(
	Boolean(ui.ownerQ || ui.ownerSource || ui.ownerArea || ui.ownerBeds || ui.ownerPtype)
)
const waiting = $derived(imports.data?.filter((r) => r.status === 'Waiting').length ?? 0)

/** v2 tabs (6 Oct, 11:20): All · My contacts · 3+ units · Next event ≤ 90 days · Just sold · Update due. */
const tabs = $derived(
	(
		[
			['all', 'All'],
			['mine', 'My contacts'],
			['multi', '3+ units'],
			['event', 'Next event ≤ 90 days'],
			['sold', 'Just sold'],
			['update', 'Update due']
		] as [OwnerTab, string][]
	).map(([id, label]) => ({ id, label, count: o?.counts[id] }))
)

const facts = $derived(
	o
		? `Agency file · ${o.on_file} owners · checked against DLD and Ejari · kept in your workspace`
		: ''
)
</script>

<svelte:head><title>Owners · CRM Beta</title></svelte:head>

<PageHeader title="Owners" {facts}>
	{#snippet note()}
		<!-- 6 Oct, 38:17–40:07: owner files stay in the agency's workspace — being built, not a promise. -->
		<span class="chip outline" title="Design principle being built (Maan), not a promise.">In build</span>
	{/snippet}
</PageHeader>

<Tabs label="Owners" items={tabs} value={ui.ownerTab} onselect={(t) => (ui.ownerTab = t)} />

<div class="filters">
	<label class="search">
		<Search size={15} />
		<span class="sr-only">Search owners</span>
		<input placeholder="Owner, unit, building" autocomplete="off" bind:value={ui.ownerQ} />
	</label>
	<FilterMenu
		label="Source"
		allLabel="All sources"
		value={ui.ownerSource}
		options={OWNER_SOURCES.map((s) => ({ id: s.id as OwnerSource, label: s.label }))}
		onselect={(v) => (ui.ownerSource = v)}
	/>
	<FilterMenu
		label="Bedrooms"
		allLabel="Any bedrooms"
		value={ui.ownerBeds}
		options={BEDS_OPTIONS}
		onselect={(v) => (ui.ownerBeds = v)}
	/>
	<FilterMenu
		label="Type"
		allLabel="Any type"
		value={ui.ownerPtype}
		options={PTYPE_OPTIONS.map((x) => ({ id: x.id as PropertyKind, label: x.label }))}
		onselect={(v) => (ui.ownerPtype = v)}
	/>
	<FilterMenu
		label="Area"
		allLabel="All areas"
		value={ui.ownerArea}
		options={(o?.areas ?? []).map((a) => ({ id: a, label: a }))}
		onselect={(v) => (ui.ownerArea = v)}
	/>
	{#if filtered}
		<button type="button" class="btn plain sm" onclick={clearOwnerFilters}>Clear</button>
	{/if}
	<span class="count" aria-live="polite">{o ? `${o.items.length} owner${o.items.length === 1 ? '' : 's'}` : ''}</span>
</div>

{#if owners.isError && o}
	<ErrorLine bar message={errorText(owners.error)} onretry={() => owners.refetch()} />
{/if}

<div class="card">
	{#if o}
		<div class="tblwrap">
			<table class="tbl">
				<thead>
					<tr><th>Owner</th><th>Units</th><th>Next event</th><th>Last contact</th><th>Record</th><th>Source</th></tr>
				</thead>
				<tbody>
					{#each o.items as x (x.id)}
						<tr class="row">
							<td>
								<button type="button" class="rowlink" onclick={() => openOwner(x.id)}>{x.name}</button>
								{#if x.tag}<Chip>{x.tag}</Chip>{/if}
								{#if x.lead}
									<div class="sub">
										Lead · {stageOf(x.lead.stage).label}{x.lead.id === null ? ` · ${x.lead.agent}` : ''}
									</div>
								{/if}
							</td>
							<td data-label="Units">
								<div>
									<div>{x.units.length}</div>
									<div class="sub">
										{x.units.slice(0, 3).join(' · ')}{x.units.length > 3 ? ` · +${x.units.length - 3}` : ''}
									</div>
								</div>
							</td>
							<td data-label="Next event">
								<div><div>{x.next_event}</div><div class="sub">{x.next_event_label}</div></div>
							</td>
							<td data-label="Last contact">
								<span class="nowrap">
									{x.last_contact}
									{#if x.market_update_due && x.prior_deal}<Chip tone="amber">Update due</Chip>{/if}
								</span>
							</td>
							<td data-label="Record">
								{#if x.prior_deal}<Chip tone="green">Prior deal</Chip>{:else}<span class="sub">None</span>{/if}
							</td>
							<td data-label="Source">
								<span class="row-chips" style:justify-content="flex-start">
									{#each x.sources as s (s)}
										<Chip tone={s === 'dld_event' ? 'blue' : 'neutral'}>
											{OWNER_SOURCES.find((v) => v.id === s)?.label}
										</Chip>
									{/each}
								</span>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="6">
								{#if filtered}
									<Empty text="No owners match.">
										<button type="button" class="btn ghost sm" onclick={clearOwnerFilters}>Clear filters</button>
									</Empty>
								{:else}
									<Empty text="No owners in this view.">
										<button type="button" class="btn ghost sm" onclick={() => panel.open({ kind: 'new-owner' })}>
											New owner
										</button>
									</Empty>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else if owners.isError}
		<ErrorLine message={errorText(owners.error)} onretry={() => owners.refetch()} />
	{:else}
		<Skeleton rows={6} />
	{/if}
</div>

<section class="card" aria-labelledby="imports-h">
	<div class="ch">
		<h2 id="imports-h">
			Owner file and import requests
			<span class="facts">Vitevue does not provide or sell owner data · {waiting} waiting for the admin</span>
		</h2>
		<button type="button" class="btn ghost sm" onclick={() => panel.open({ kind: 'new-import' })}>
			Import a file
		</button>
	</div>
	<QueryView query={imports} rows={2}>
		{#snippet children(list)}
			{#if list.length}
				<div class="tblwrap">
					<table class="tbl">
						<thead><tr><th>File</th><th>What</th><th>Areas</th><th>Sent</th><th>Status</th></tr></thead>
						<tbody>
							{#each list as r (r.id)}
								<tr>
									<td class="nm mono">{r.file}</td>
									<td data-label="What">{r.kind} · {fmt(r.rows)} rows</td>
									<td class="sub" data-label="Areas">{r.areas}</td>
									<td class="sub" data-label="Sent">{r.who} · {r.at}</td>
									<td data-label="Status"><Chip tone={r.tone}>{r.status}</Chip></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<Empty text="No import requests. Send a CSV of owners or leads for the admin to approve." />
			{/if}
		{/snippet}
	</QueryView>
</section>
