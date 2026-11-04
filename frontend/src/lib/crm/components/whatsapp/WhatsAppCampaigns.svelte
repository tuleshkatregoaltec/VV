<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/plus'
import Search from 'lucide-svelte/icons/search'
import Send from 'lucide-svelte/icons/send'
import { crm } from '../../api'
import type { WhatsAppAudienceLead } from '../../api/types'
import { INTENT_LABEL, stamp } from '../../email'
import { plural } from '../../format'
import { crmQueries } from '../../queries'
import { openLead } from '../../stores/panel.svelte'
import {
	FIRST_NAME,
	fillValues,
	messageTitle,
	RECIPIENT_STATUS,
	variableCount
} from '../../whatsapp'
import { errorText, write } from '../../write'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import Skeleton from '../ui/Skeleton.svelte'

/**
 * Connectors › WhatsApp › Campaigns (organization owners): one approved template, sent once to
 * each chosen lead from the campaign number. Only leads with consent recorded and no opt-out can
 * be chosen; the backend checks again just before each send.
 */
const uid = $props.id()
const campaigns = createQuery(() => crmQueries.whatsappCampaigns())
let openId = $state<number | null>(null)
const detail = createQuery(() => ({
	...crmQueries.whatsappCampaign(openId ?? 0),
	enabled: openId !== null
}))

/* ── new campaign ── */
let composing = $state(false)
let name = $state('')
const templates = createQuery(() => crmQueries.whatsappTemplates())
const approved = $derived((templates.data ?? []).filter((t) => t.review === 'approved'))
let templateKey = $state('')
const template = $derived(approved.find((t) => `${t.name}:${t.language}` === templateKey))
let values = $state<string[]>([])
$effect(() => {
	values = template
		? Array.from({ length: variableCount(template.body) }, (_, i) => (i === 0 ? FIRST_NAME : ''))
		: []
})
let q = $state('')
let intent = $state('')
const audience = createQuery(() => ({
	...crmQueries.whatsappAudience({ search: q, intent }),
	enabled: composing
}))
const leads = $derived(audience.data?.items ?? [])
let chosen = $state<number[]>([])
const allOn = $derived(leads.length > 0 && leads.every((l) => chosen.includes(l.id)))
const firstChosen = $derived(leads.find((l) => chosen.includes(l.id)))
let sending = $state(false)
const ready = $derived(
	Boolean(name.trim() && template && chosen.length && values.every((v) => v.trim()))
)

function toggle(id: number) {
	chosen = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id]
}
function toggleAll() {
	const ids = leads.map((l) => l.id)
	chosen = allOn ? chosen.filter((x) => !ids.includes(x)) : [...new Set([...chosen, ...ids])]
}
/** The preview uses the first chosen lead's first name for {first_name}. */
function preview(l: WhatsAppAudienceLead | undefined) {
	if (!template) return ''
	const first = l?.name.trim().split(/\s+/)[0] ?? 'Asha'
	return fillValues(
		template.body,
		values.map((v) => (v.trim() === FIRST_NAME ? first : v))
	)
}

async function submit(e: SubmitEvent) {
	e.preventDefault()
	if (!template || !ready) return
	sending = true
	const r = await write({
		call: () =>
			crm.whatsapp.campaigns.create({
				name: name.trim(),
				template_name: template.name,
				language: template.language,
				params: values.map((v) => v.trim()),
				enquiry_ids: chosen
			}),
		success: (c) => `Campaign started: sending to ${plural(c.counts.total, 'lead')}`
	})
	sending = false
	if (r) {
		composing = false
		name = ''
		templateKey = ''
		chosen = []
		openId = r.id
	}
}

async function resume(id: number) {
	await write({ call: () => crm.whatsapp.campaigns.resume(id), success: 'Sending the rest' })
}
</script>

<div class="filters">
	<span class="sub">
		Promotions go out from the campaign number, only to leads who agreed to them. A tap on "Stop
		promotions" or a reply of STOP removes them from every future campaign.
	</span>
	<span class="wa-grow"></span>
	{#if !composing}
		<button type="button" class="btn sm" onclick={() => (composing = true)}>
			<Plus size={14} /> New campaign
		</button>
	{/if}
</div>

{#if composing}
	<form class="card form wa-new" onsubmit={submit}>
		<div class="fld">
			<label for="{uid}-name">Campaign name</label>
			<input id="{uid}-name" bind:value={name} maxlength="120" placeholder="Dubai Marina · new listings" />
		</div>
		<div class="fld">
			<label for="{uid}-tpl">Approved message</label>
			<select id="{uid}-tpl" bind:value={templateKey} disabled={!approved.length}>
				<option value="">{approved.length ? 'Choose a message' : 'No approved messages yet'}</option>
				{#each approved as tp (`${tp.name}:${tp.language}`)}
					<option value="{tp.name}:{tp.language}">
						{messageTitle(tp.name)} · {tp.category} · {tp.language}
					</option>
				{/each}
			</select>
		</div>
		{#each values as _, i (i)}
			<div class="fld">
				<label for="{uid}-v{i}">
					Value {i + 1}
					{#if values[i] === FIRST_NAME}<span class="sub">· each lead's first name</span>{/if}
				</label>
				<input id="{uid}-v{i}" bind:value={values[i]} maxlength="200" />
			</div>
		{/each}
		{#if template}
			<div class="msg me wa-preview">
				<div class="w">Preview{firstChosen ? ` for ${firstChosen.name}` : ''}</div>
				<div class="wa-body">{preview(firstChosen)}</div>
			</div>
		{/if}

		<div class="lbl">Who it goes to</div>
		<div class="filters">
			<label class="search">
				<Search size={15} />
				<span class="sr-only">Search leads</span>
				<input placeholder="Name or phone" autocomplete="off" bind:value={q} />
			</label>
			<select bind:value={intent} aria-label="Lead type">
				<option value="">Every type</option>
				{#each Object.entries(INTENT_LABEL) as [key, label] (key)}
					<option value={key}>{label}</option>
				{/each}
			</select>
		</div>
		{#if audience.data}
			<div class="sub">
				Only leads who agreed to promotions are listed. Left out: {plural(audience.data.no_consent, 'lead')}
				without consent · {audience.data.opted_out} opted out · {audience.data.no_number} without a WhatsApp number.
			</div>
			<div class="tblwrap wa-aud">
				<table class="tbl">
					<thead>
						<tr>
							<th><input type="checkbox" aria-label="Choose all" checked={allOn} onchange={toggleAll} /></th>
							<th>Lead</th><th>Type</th><th>Source</th>
						</tr>
					</thead>
					<tbody>
						{#each leads as l (l.id)}
							<tr class="row">
								<td><input type="checkbox" aria-label="Choose {l.name}" checked={chosen.includes(l.id)} onchange={() => toggle(l.id)} /></td>
								<td>{l.name}<div class="sub">{l.wa_number}</div></td>
								<td>{INTENT_LABEL[l.intent]}</td>
								<td class="sub">{l.source}</td>
							</tr>
						{:else}
							<tr><td colspan="4"><Empty text="No leads with consent match." /></td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else if audience.isError}
			<ErrorLine message={errorText(audience.error)} onretry={() => audience.refetch()} />
		{:else}
			<Skeleton rows={3} />
		{/if}

		<div class="form-actions">
			<button type="button" class="btn ghost sm" onclick={() => (composing = false)}>Cancel</button>
			<span class="wa-grow"></span>
			<button type="submit" class="btn sm" disabled={sending || !ready}>
				<Send size={14} />
				{sending ? 'Starting…' : `Send to ${plural(chosen.length, 'lead')}`}
			</button>
		</div>
	</form>
{/if}

{#if campaigns.data}
	<div class="card">
		<div class="tblwrap">
			<table class="tbl">
				<thead>
					<tr><th>Campaign</th><th>Sent</th><th>Delivered</th><th>Read</th><th>Replies</th><th>Failed</th><th>Status</th><th>When</th></tr>
				</thead>
				<tbody>
					{#each campaigns.data as c (c.id)}
						<tr class="row">
							<td>
								<button type="button" class="rowlink" onclick={() => (openId = openId === c.id ? null : c.id)}>{c.name}</button>
								<div class="sub">{messageTitle(c.template_name)} · {plural(c.counts.total, 'lead')}</div>
							</td>
							<td data-label="Sent">{c.counts.sent + c.counts.delivered + c.counts.read}</td>
							<td data-label="Delivered">{c.counts.delivered + c.counts.read}</td>
							<td data-label="Read">{c.counts.read}</td>
							<td data-label="Replies">{c.counts.replies}</td>
							<td data-label="Failed">{c.counts.failed}</td>
							<td data-label="Status">
								{#if c.status === 'sending'}
									<Chip tone="blue">Sending · {c.counts.total - c.counts.pending}/{c.counts.total}</Chip>
								{:else}
									<Chip tone="green">Completed</Chip>
								{/if}
							</td>
							<td data-label="When" class="nowrap">{stamp(c.created_at)}</td>
						</tr>
					{:else}
						<tr><td colspan="8"><Empty text="No campaigns yet." /></td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{:else if campaigns.isError}
	<div class="card"><ErrorLine message={errorText(campaigns.error)} onretry={() => campaigns.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={3} /></div>
{/if}

{#if openId !== null && detail.data}
	{@const d = detail.data}
	<div class="card wa-detail">
		<div class="filters">
			<strong>{d.name}</strong>
			<span class="sub">{messageTitle(d.template_name)} · {d.template_language}</span>
			<span class="wa-grow"></span>
			{#if d.status === 'sending'}
				<button type="button" class="btn ghost sm" onclick={() => resume(d.id)}>Resume sending</button>
			{/if}
		</div>
		{#if d.counts.unknown}
			<div class="notice">
				{plural(d.counts.unknown, 'message')} were interrupted while sending and may or may not have
				arrived. Check those chats before contacting them again.
			</div>
		{/if}
		<div class="tblwrap">
			<table class="tbl">
				<thead><tr><th>Lead</th><th>Status</th><th>Note</th></tr></thead>
				<tbody>
					{#each d.recipients as r (r.wa_number)}
						{@const s = RECIPIENT_STATUS[r.status] ?? { label: r.status, tone: 'neutral' }}
						<tr class="row">
							<td>
								{#if r.enquiry_id}
									<button type="button" class="rowlink" onclick={() => r.enquiry_id && openLead(r.enquiry_id, 'conversation')}>{r.name}</button>
								{:else}{r.name}{/if}
								<div class="sub">{r.wa_number}</div>
							</td>
							<td data-label="Status"><Chip tone={s.tone}>{s.label}</Chip></td>
							<td data-label="Note" class="sub">{r.error ?? ''}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{/if}

<style>
	.wa-grow {
		flex: 1;
	}
	.wa-new,
	.wa-detail {
		display: grid;
		gap: 0.6rem;
		padding: 1rem;
		margin-bottom: 1rem;
	}
	.wa-aud {
		max-height: 320px;
		overflow: auto;
	}
	.wa-preview {
		justify-self: end;
	}
	.wa-body {
		white-space: pre-wrap;
		margin-top: 4px;
	}
	.lbl {
		font-weight: 600;
	}
</style>
