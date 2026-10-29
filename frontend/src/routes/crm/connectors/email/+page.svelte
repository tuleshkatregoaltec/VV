<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import PenLine from 'lucide-svelte/icons/pen-line'
import Plus from 'lucide-svelte/icons/plus'
import RefreshCw from 'lucide-svelte/icons/refresh-cw'
import Search from 'lucide-svelte/icons/search'
import Trash2 from 'lucide-svelte/icons/trash-2'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { crm } from '$lib/crm/api'
import type { EmailLead, EmailSendStatus } from '$lib/crm/api/types'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import FilterMenu from '$lib/crm/components/ui/FilterMenu.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import {
	EVENT_LABEL,
	INTENT_LABEL,
	INTENT_ORDER,
	SEND_STATUS,
	SEND_STATUS_ORDER,
	stamp,
	statusLabel,
	suits
} from '$lib/crm/email'
import { confirmDeleteSend } from '$lib/crm/emailActions'
import { plural } from '$lib/crm/format'
import { crmQueries } from '$lib/crm/queries'
import { openLead, panel } from '$lib/crm/stores/panel.svelte'
import { errorText, write } from '$lib/crm/write'

/**
 * Connectors › Email (spec 2026-10-28): email CRM leads of any type that have an email address
 * (marketing, reports, updates), track what happened, and keep company-wide templates.
 * One Brevo account, configured on the server.
 */
type Tab = 'leads' | 'inbox' | 'tracking' | 'templates'
const TABS: Tab[] = ['leads', 'inbox', 'tracking', 'templates']
const tab = $derived<Tab>(TABS.find((t) => t === page.url.searchParams.get('tab')) ?? 'leads')

function selectTab(id: Tab) {
	const url = new URL(page.url)
	if (id === 'leads') url.searchParams.delete('tab')
	else url.searchParams.set('tab', id)
	goto(url, { replaceState: true, noScroll: true, keepFocus: true })
}

const status = createQuery(() => crmQueries.emailStatus())

/* ── leads ── */
let q = $state('')
let intent = $state<EmailLead['intent'] | ''>('')
let source = $state('')
const leads = createQuery(() => crmQueries.emailLeads({ search: q, intent, source }))
const rows = $derived(leads.data?.items ?? [])
const filtered = $derived(Boolean(q.trim() || intent || source))
let selected = $state<number[]>([])
const selectable = $derived(rows.filter((l) => !l.do_not_contact))
const allOn = $derived(selectable.length > 0 && selectable.every((l) => selected.includes(l.id)))

function toggle(id: number) {
	selected = selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]
}
function toggleAll() {
	const ids = selectable.map((l) => l.id)
	selected = allOn ? selected.filter((x) => !ids.includes(x)) : [...new Set([...selected, ...ids])]
}

/* ── inbox ── */
const inbound = createQuery(() => crmQueries.emailInbound())

/* ── templates ── */
const templates = createQuery(() => crmQueries.emailTemplates())
let templateType = $state<EmailLead['intent'] | ''>('')
/** A type filter keeps templates for that type, including those for every type. */
const shownTemplates = $derived(
	(templates.data ?? []).filter((t) => !templateType || suits(t.lead_types, [templateType]))
)

/* ── tracking ── */
let filter = $state<EmailSendStatus | ''>('')
const sends = createQuery(() => crmQueries.emailSends(filter))
const counts = $derived(sends.data?.counts ?? {})
const total = $derived(Object.values(counts).reduce((a, n) => a + (n ?? 0), 0))
let syncing = $state(false)

async function sync() {
	syncing = true
	await write({
		call: () => crm.email.sync(),
		success: (r) =>
			r.applied
				? `${plural(r.applied, 'new event')} from Brevo`
				: r.fetched
					? 'Up to date: no new events'
					: 'Brevo has no events for these emails yet'
	})
	syncing = false
}

const facts = $derived(
	status.data
		? status.data.configured
			? `From ${status.data.sender_name ?? ''} <${status.data.sender_email}> · ${status.data.webhook_configured ? 'live tracking on' : 'tracking by Sync'}`
			: 'Email your leads: marketing, reports and updates, with opens and clicks tracked'
		: ''
)
</script>

<svelte:head><title>Email · Connectors · CRM Beta</title></svelte:head>

<PageHeader title="Email" {facts}>
	{#snippet right()}
		<a class="btn ghost sm" href="/crm/connectors"><ArrowLeft size={14} /> Connectors</a>
	{/snippet}
</PageHeader>

<Tabs
	label="Email"
	items={[
		{ id: 'leads', label: 'Leads', count: leads.data?.total ?? null },
		{ id: 'inbox', label: 'Inbox', count: inbound.data?.total ?? null },
		{ id: 'tracking', label: 'Tracking', count: sends.data ? total : null },
		{ id: 'templates', label: 'Templates', count: templates.data?.length ?? null }
	]}
	value={tab}
	onselect={selectTab}
/>

{#if tab === 'leads'}
	<div class="filters">
		<label class="search">
			<Search size={15} />
			<span class="sr-only">Search leads</span>
			<input placeholder="Name, email, phone" autocomplete="off" bind:value={q} />
		</label>
		<FilterMenu
			label="Type"
			allLabel="All types"
			value={intent}
			options={INTENT_ORDER.map((i) => ({ id: i, label: INTENT_LABEL[i] }))}
			onselect={(v) => (intent = v)}
		/>
		<FilterMenu
			label="Source"
			allLabel="All sources"
			value={source}
			options={(leads.data?.sources ?? []).map((s) => ({ id: s, label: s }))}
			onselect={(v) => (source = v)}
		/>
		<span class="em-grow"></span>
		<button
			type="button"
			class="btn sm"
			onclick={() => panel.open({ kind: 'email-compose', leadIds: selected })}
		>
			<PenLine size={14} />
			{selected.length ? `Compose to ${plural(selected.length, 'lead')}` : 'Compose'}
		</button>
	</div>

	{#if leads.data}
		<div class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th class="em-ck">
								<input type="checkbox" aria-label="Select all" checked={allOn} onchange={toggleAll} />
							</th>
							<th>Lead</th><th>Type</th><th>Source</th><th>Stage</th><th>Last email</th>
						</tr>
					</thead>
					<tbody>
						{#each rows as l (l.id)}
							<tr class="row">
								<td class="em-ck">
									<input
										type="checkbox"
										aria-label="Select {l.name}"
										disabled={l.do_not_contact}
										checked={selected.includes(l.id)}
										onchange={() => toggle(l.id)}
									/>
								</td>
								<td>
									<button
										type="button"
										class="rowlink"
										onclick={() => openLead(l.id)}
									>
										{l.name}
									</button>
									<div class="sub">{l.email}</div>
								</td>
								<td data-label="Type">{INTENT_LABEL[l.intent]}</td>
								<td data-label="Source" class="sub">{l.source}</td>
								<td data-label="Stage">
									{statusLabel(l.status)}
									{#if l.do_not_contact}<div><Chip tone="amber">Do not contact</Chip></div>{/if}
								</td>
								<td data-label="Last email">
									{#if l.last_status}
										<Chip tone={SEND_STATUS[l.last_status].tone}>{SEND_STATUS[l.last_status].label}</Chip>
										<div class="sub">{stamp(l.last_sent_at)} · {plural(l.sends, 'email')}</div>
									{:else}
										<span class="sub">Not emailed yet</span>
									{/if}
								</td>
							</tr>
						{:else}
							<tr>
								<td colspan="6">
									<Empty
										text={filtered
											? 'No leads with an email match these filters.'
											: 'No leads have an email yet. Add an email on a lead to reach it from here.'}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{#if leads.data.total > rows.length}
			<p class="small muted">Showing {rows.length} of {leads.data.total}. Search or filter to narrow.</p>
		{/if}
		{#if leads.isError}
			<ErrorLine bar message={errorText(leads.error)} onretry={() => leads.refetch()} />
		{/if}
	{:else if leads.isError}
		<div class="card"><ErrorLine message={errorText(leads.error)} onretry={() => leads.refetch()} /></div>
	{:else}
		<div class="card"><Skeleton rows={6} /></div>
	{/if}
{:else if tab === 'inbox'}
	<div class="filters">
		<span class="sub">
			Replies to your emails and new emails sent to your inbound address. Unknown senders become new leads in the Inbox.
		</span>
	</div>

	{#if inbound.data}
		<div class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr><th>From</th><th>Email</th><th>Lead</th><th>Received</th></tr>
					</thead>
					<tbody>
						{#each inbound.data.items as m (m.id)}
							<tr class="row">
								<td>
									<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'email-inbound', id: m.id })}>
										{m.from_name ?? m.from_email}
									</button>
									<div class="sub">{m.from_email}</div>
								</td>
								<td data-label="Email">
									<div>{m.subject}</div>
									<span class="sub em-clip">{m.body}</span>
								</td>
								<td data-label="Lead">
									{#if m.enquiry_id !== null}
										<button type="button" class="btn plain sm" onclick={() => m.enquiry_id && openLead(m.enquiry_id)}>
											{m.lead_name ?? 'Open lead'}
										</button>
									{/if}
									{#if m.created_lead}<Chip tone="blue">New lead</Chip>{:else if m.send_id}<Chip tone="green">Reply</Chip>{/if}
								</td>
								<td data-label="Received" class="nowrap">{stamp(m.received_at)}</td>
							</tr>
						{:else}
							<tr>
								<td colspan="4"><Empty text="No emails received yet. Replies to your emails land here." /></td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{#if inbound.isError}
			<ErrorLine bar message={errorText(inbound.error)} onretry={() => inbound.refetch()} />
		{/if}
	{:else if inbound.isError}
		<div class="card"><ErrorLine message={errorText(inbound.error)} onretry={() => inbound.refetch()} /></div>
	{:else}
		<div class="card"><Skeleton rows={4} /></div>
	{/if}
{:else if tab === 'templates'}
	<div class="filters">
		<FilterMenu
			label="Type"
			allLabel="All types"
			value={templateType}
			options={INTENT_ORDER.map((i) => ({ id: i, label: INTENT_LABEL[i] }))}
			onselect={(v) => (templateType = v)}
		/>
		<span class="sub">Shared with your company. Compose suggests each one for the types it is for.</span>
		<span class="em-grow"></span>
		<button type="button" class="btn sm" onclick={() => panel.open({ kind: 'email-template' })}>
			<Plus size={14} /> New template
		</button>
	</div>

	{#if templates.data}
		<div class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr><th>Template</th><th>For</th><th>Subject</th><th>Message</th><th>Updated</th></tr>
					</thead>
					<tbody>
						{#each shownTemplates as t (t.id)}
							<tr class="row">
								<td>
									<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'email-template', id: t.id })}>
										{t.name}
									</button>
								</td>
								<td data-label="For">
									{#if t.lead_types.length}
										<div class="em-types">
											{#each t.lead_types as i (i)}<Chip tone="outline">{INTENT_LABEL[i]}</Chip>{/each}
										</div>
									{:else}<span class="sub">All types</span>{/if}
								</td>
								<td data-label="Subject">{t.subject}</td>
								<td data-label="Message"><span class="sub em-clip">{t.body}</span></td>
								<td data-label="Updated" class="nowrap">{stamp(t.updated_at)}</td>
							</tr>
						{:else}
							<tr>
								<td colspan="5">
									<Empty
										text={templateType
											? `No template for ${INTENT_LABEL[templateType]} leads yet.`
											: 'No templates yet. Write one to reuse it in Compose.'}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{#if templates.isError}
			<ErrorLine bar message={errorText(templates.error)} onretry={() => templates.refetch()} />
		{/if}
	{:else if templates.isError}
		<div class="card"><ErrorLine message={errorText(templates.error)} onretry={() => templates.refetch()} /></div>
	{:else}
		<div class="card"><Skeleton rows={4} /></div>
	{/if}
{:else}
	<div class="filters">
		<FilterMenu
			label="Status"
			allLabel="All statuses"
			value={filter}
			options={SEND_STATUS_ORDER.map((s) => ({ id: s, label: `${SEND_STATUS[s].label} · ${counts[s] ?? 0}` }))}
			onselect={(v) => (filter = v)}
		/>
		<span class="em-grow"></span>
		<button type="button" class="btn ghost sm" disabled={syncing || status.data?.configured === false} onclick={sync}>
			<RefreshCw size={14} />
			{syncing ? 'Syncing…' : 'Sync from Brevo'}
		</button>
	</div>

	{#if sends.data}
		<div class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Recipient</th><th>Subject</th><th>Status</th><th class="r">Opens</th><th class="r">Clicks</th
							><th>Sent</th><th>Last event</th><th><span class="sr-only">Delete</span></th>
						</tr>
					</thead>
					<tbody>
						{#each sends.data.items as s (s.id)}
							{@const last = s.events.at(-1)}
							<tr class="row">
								<td>
									<button type="button" class="rowlink" onclick={() => panel.open({ kind: 'email-send', id: s.id })}>
										{s.to_name ?? s.to_email}
									</button>
									<div class="sub">{s.to_email}</div>
								</td>
								<td data-label="Subject">{s.subject}</td>
								<td data-label="Status">
									<Chip tone={SEND_STATUS[s.status].tone}>{SEND_STATUS[s.status].label}</Chip>
									{#if s.error}<div class="sub em-err">{s.error}</div>{/if}
								</td>
								<td class="r" data-label="Opens">{s.opens}</td>
								<td class="r" data-label="Clicks">{s.clicks}</td>
								<td data-label="Sent" class="nowrap">{stamp(s.sent_at ?? s.created_at)}</td>
								<td data-label="Last event">
									{#if last}
										{EVENT_LABEL[last.event] ?? last.event}
										<div class="sub">{stamp(last.at)}</div>
									{:else}<span class="sub">—</span>{/if}
								</td>
								<td class="r">
									<button
										type="button"
										class="btn plain sm"
										aria-label="Delete {s.subject} to {s.to_email}"
										title="Delete from Tracking"
										onclick={() => confirmDeleteSend(s)}
									>
										<Trash2 size={14} />
									</button>
								</td>
							</tr>
						{:else}
							<tr>
								<td colspan="8">
									<Empty
										text={filter ? 'No emails with this status.' : 'Nothing sent yet. Pick leads and send an email first.'}
									/>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
		{#if sends.isError}
			<ErrorLine bar message={errorText(sends.error)} onretry={() => sends.refetch()} />
		{/if}
	{:else if sends.isError}
		<div class="card"><ErrorLine message={errorText(sends.error)} onretry={() => sends.refetch()} /></div>
	{:else}
		<div class="card"><Skeleton rows={6} /></div>
	{/if}
{/if}

<style>
	.em-clip {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		max-width: 420px;
	}
	.em-types {
		display: flex;
		flex-wrap: wrap;
		gap: 4px;
	}
	.em-grow {
		flex: 1;
	}
	.em-ck {
		width: 32px;
	}
	.em-err {
		color: var(--red);
		max-width: 260px;
	}
</style>
