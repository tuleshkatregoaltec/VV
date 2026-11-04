<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/plus'
import { organizationQueries } from '$lib/queries/organization'
import { crm } from '../../api'
import type { WhatsAppNumber } from '../../api/types'
import { crmQueries } from '../../queries'
import { errorText, write } from '../../write'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import Skeleton from '../ui/Skeleton.svelte'

/**
 * Connectors › WhatsApp › Numbers (organization owners): which agent sends from which registered
 * number, and the one campaign number. An agent sees WhatsApp only once a number is theirs.
 */
let { connected }: { connected: boolean } = $props()

const uid = $props.id()
const numbers = createQuery(() => crmQueries.whatsappNumbers())
const meta = createQuery(() => ({ ...crmQueries.whatsappMetaNumbers(), enabled: connected }))
const members = createQuery(() => organizationQueries.members(true))

const memberName = (id: string | null) => {
	const m = members.data?.find((x) => x.id === id)
	return m ? `${m.first_name} ${m.last_name}`.trim() || m.email : id ? 'Unknown user' : '—'
}

/* ── add or change ── */
let editing = $state(false)
let phoneNumberId = $state('')
let label = $state('')
let purpose = $state<'agent' | 'campaign'>('agent')
let userId = $state('')
let active = $state(true)
let saving = $state(false)
const metaNumber = $derived(meta.data?.find((n) => n.phone_number_id === phoneNumberId))
const existing = $derived(numbers.data?.find((n) => n.phone_number_id === phoneNumberId))
const ready = $derived(Boolean(phoneNumberId && label.trim() && (purpose === 'campaign' || userId)))

function start(n?: WhatsAppNumber) {
	editing = true
	phoneNumberId = n?.phone_number_id ?? ''
	label = n?.label ?? ''
	purpose = n?.purpose ?? 'agent'
	userId = n?.user_id ?? ''
	active = n?.active ?? true
}

$effect(() => {
	// A newly picked number suggests its own name as the label.
	if (metaNumber && !existing && !label) label = metaNumber.verified_name ?? ''
})

async function save(e: SubmitEvent) {
	e.preventDefault()
	if (!ready) return
	saving = true
	const r = await write({
		call: () =>
			crm.whatsapp.numbers.save(phoneNumberId, {
				display_number: metaNumber?.display_number ?? existing?.display_number ?? phoneNumberId,
				label: label.trim(),
				purpose,
				user_id: purpose === 'agent' ? userId : null,
				active
			}),
		success: 'WhatsApp number saved'
	})
	saving = false
	if (r) editing = false
}
</script>

<div class="filters">
	<span class="sub">
		Each agent sends from their own number, so a contact sees a separate chat per agent. One number
		can be the campaign number, for promotions.
	</span>
	<span class="wa-grow"></span>
	{#if !editing && connected}
		<button type="button" class="btn sm" onclick={() => start()}><Plus size={14} /> Add number</button>
	{/if}
</div>

{#if !connected}
	<div class="notice">
		WhatsApp is not connected on the server yet, so Meta's numbers cannot be read. Set the
		WHATSAPP_* settings first (see docs/whatsapp-setup.md).
	</div>
{/if}

{#if editing}
	<form class="card form wa-form" onsubmit={save}>
		<div class="fld">
			<label for="{uid}-num">Number</label>
			{#if existing}
				<input id="{uid}-num" value="{existing.display_number} · {existing.phone_number_id}" disabled />
			{:else}
				<select id="{uid}-num" bind:value={phoneNumberId} disabled={!meta.data}>
					<option value="">{meta.data ? 'Choose a number from Meta' : 'Loading Meta numbers…'}</option>
					{#each meta.data ?? [] as n (n.phone_number_id)}
						<option value={n.phone_number_id} disabled={numbers.data?.some((x) => x.phone_number_id === n.phone_number_id)}>
							{n.display_number} · {n.verified_name ?? 'no name'}{numbers.data?.some((x) => x.phone_number_id === n.phone_number_id) ? ' (registered)' : ''}
						</option>
					{/each}
				</select>
				{#if meta.isError}<ErrorLine message={errorText(meta.error)} onretry={() => meta.refetch()} />{/if}
			{/if}
		</div>
		<div class="fld">
			<label for="{uid}-label">Label</label>
			<input id="{uid}-label" bind:value={label} maxlength="120" placeholder="Vitevue · Sara" />
		</div>
		<div class="fld">
			<label for="{uid}-purpose">Used for</label>
			<select id="{uid}-purpose" bind:value={purpose}>
				<option value="agent">An agent's chats</option>
				<option value="campaign">Campaigns (promotions)</option>
			</select>
		</div>
		{#if purpose === 'agent'}
			<div class="fld">
				<label for="{uid}-agent">Agent</label>
				<select id="{uid}-agent" bind:value={userId}>
					<option value="">Choose an agent</option>
					{#each members.data ?? [] as m (m.id)}
						<option value={m.id}>{`${m.first_name} ${m.last_name}`.trim() || m.email} · {m.email}</option>
					{/each}
				</select>
			</div>
		{/if}
		<label class="wa-check"><input type="checkbox" bind:checked={active} /> Active</label>
		<div class="form-actions">
			<button type="button" class="btn ghost sm" onclick={() => (editing = false)}>Cancel</button>
			<span class="wa-grow"></span>
			<button type="submit" class="btn sm" disabled={saving || !ready}>{saving ? 'Saving…' : 'Save number'}</button>
		</div>
	</form>
{/if}

{#if numbers.data}
	<div class="card">
		<div class="tblwrap">
			<table class="tbl">
				<thead><tr><th>Number</th><th>Label</th><th>Used by</th><th>Status</th><th></th></tr></thead>
				<tbody>
					{#each numbers.data as n (n.phone_number_id)}
						<tr class="row">
							<td>{n.display_number}<div class="sub">ID {n.phone_number_id}</div></td>
							<td data-label="Label">{n.label}</td>
							<td data-label="Used by">{n.purpose === 'campaign' ? 'Campaigns' : memberName(n.user_id)}</td>
							<td data-label="Status">
								{#if n.active}<Chip tone="green">Active</Chip>{:else}<Chip tone="neutral">Off</Chip>{/if}
							</td>
							<td><button type="button" class="btn ghost sm" onclick={() => start(n)}>Change</button></td>
						</tr>
					{:else}
						<tr><td colspan="5"><Empty text="No numbers yet. Add one so agents can message from the CRM." /></td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{:else if numbers.isError}
	<div class="card"><ErrorLine message={errorText(numbers.error)} onretry={() => numbers.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={3} /></div>
{/if}

<style>
	.wa-grow {
		flex: 1;
	}
	.wa-form {
		display: grid;
		gap: 0.6rem;
		padding: 1rem;
		margin-bottom: 1rem;
	}
	.wa-check {
		display: flex;
		align-items: center;
		gap: 6px;
	}
</style>
