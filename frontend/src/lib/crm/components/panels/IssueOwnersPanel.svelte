<script lang="ts">
/**
 * Owner sheet → "Issue as outbound leads": the sheet's owners become leads for agents to contact
 * (one per owner, with their contact details and the unit they own), routed with the same choices
 * as a Leads import. Owners already issued keep their lead; ones an agent holds are left alone.
 */
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type { ImportAssignment } from '../../api/types'
import { fmt } from '../../format'
import { panel } from '../../stores/panel.svelte'
import { write } from '../../write'
import AssignmentPicker from '../ui/AssignmentPicker.svelte'
import Panel from '../ui/Panel.svelte'

let { listId, name }: { listId: number; name: string } = $props()

type Status = 'verified_current_owner' | 'probable_current_owner' | ''
const STATUSES: { id: Status; label: string }[] = [
	{ id: 'verified_current_owner', label: 'Verified current owners' },
	{ id: 'probable_current_owner', label: 'Probable current owners' },
	{ id: '', label: 'Every owner in the sheet' }
]
const MAX = 500

let status = $state<Status>('verified_current_owner')
let limit = $state(100)
let assignment = $state<ImportAssignment | null>(null)
let sending = $state(false)
let remaining = $state<number | null>(null)
/** Where the next batch starts after one has been issued. */
let offset = $state(0)
const validLimit = $derived(Number.isInteger(limit) && limit >= 1 && limit <= MAX)

function summary(r: Awaited<ReturnType<typeof crm.owners.issue>>): string {
	const parts = [`${fmt(r.issued)} ${r.issued === 1 ? 'owner' : 'owners'} issued`]
	if (r.assignment.assigned) parts.push(`${fmt(r.assignment.assigned)} assigned`)
	if (r.assignment.shared) parts.push(`${fmt(r.assignment.shared)} shared with the team`)
	const waiting = (r.assignment.unassigned ?? 0) - (r.assignment.shared ?? 0)
	if (waiting > 0) parts.push(`${fmt(waiting)} waiting in the Inbox`)
	if (r.already_assigned) parts.push(`${fmt(r.already_assigned)} already with an agent`)
	if (r.skipped) parts.push(`${fmt(r.skipped)} skipped (no phone or email)`)
	return parts.join(' · ')
}

async function send() {
	const policy = assignment
	if (!policy || !validLimit || sending) return
	sending = true
	const r = await write({
		domain: 'leads',
		call: () => crm.owners.issue(listId, { status: status || null, limit, offset }, policy),
		success: summary,
		undoable: false
	})
	sending = false
	if (r) {
		remaining = r.remaining
		offset = r.next_offset ?? 0
		if (!r.remaining) panel.closeAll()
	}
}
</script>

<Panel kicker="Owner sheet" title="Issue as outbound leads" sub={name}>
	<div class="form">
		<p class="small muted">
			Each owner becomes a lead for agents to contact, with their phone, email and the unit they
			own. Issuing the same owner again reuses their lead.
		</p>
		<div class="fld">
			<label for="issue-owner-status">Which owners</label>
			<select
				id="issue-owner-status"
				bind:value={status}
				disabled={sending}
				onchange={() => {
					offset = 0
					remaining = null
				}}
			>
				{#each STATUSES as s (s.id)}<option value={s.id}>{s.label}</option>{/each}
			</select>
		</div>
		<div class="fld">
			<label for="issue-owner-limit">How many (up to {MAX} at a time)</label>
			<input id="issue-owner-limit" type="number" min="1" max={MAX} bind:value={limit} disabled={sending} />
		</div>
		<AssignmentPicker bind:assignment disabled={sending} noun="leads" id="issue-owners" />
		{#if remaining}
			<div class="notice" role="status">
				{fmt(remaining)} more owners in this sheet match. Issue again to continue with the next batch.
			</div>
		{/if}
		<div class="actions">
			<button type="button" class="btn" disabled={!assignment || !validLimit || sending} onclick={send}>
				{sending ? 'Issuing…' : remaining ? 'Issue the next batch' : 'Issue to agents'}
			</button>
			<button type="button" class="btn ghost" onclick={() => goto('/crm/inbox')}>Open Inbox</button>
		</div>
	</div>
</Panel>

<style>
	.form {
		display: grid;
		gap: 16px;
	}
	.actions {
		display: flex;
		gap: 8px;
	}
</style>
