<script lang="ts">
/**
 * Assets › Renewals → "Issue to agents": the units a manager ticked become outbound leads (one
 * shared lead per unit, as when an agent opens it) routed with the same choices as a Leads
 * import. Leads an agent already holds are left with them.
 */
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type { ImportAssignment } from '../../api/types'
import { fmt } from '../../format'
import { panel } from '../../stores/panel.svelte'
import { ui } from '../../stores/ui.svelte'
import { write } from '../../write'
import AssignmentPicker from '../ui/AssignmentPicker.svelte'
import Panel from '../ui/Panel.svelte'

let assignment = $state<ImportAssignment | null>(null)
let sending = $state(false)
const count = $derived(ui.renewalSelected.length)

function summary(r: Awaited<ReturnType<typeof crm.renewals.issue>>): string {
	const parts = [`${fmt(r.issued)} ${r.issued === 1 ? 'unit' : 'units'} issued`]
	if (r.assignment.assigned) parts.push(`${fmt(r.assignment.assigned)} assigned`)
	if (r.assignment.shared) parts.push(`${fmt(r.assignment.shared)} shared with the team`)
	const waiting = (r.assignment.unassigned ?? 0) - (r.assignment.shared ?? 0)
	if (waiting > 0) parts.push(`${fmt(waiting)} waiting in the Inbox`)
	if (r.already_assigned) parts.push(`${fmt(r.already_assigned)} already with an agent`)
	if (r.skipped) parts.push(`${fmt(r.skipped)} skipped (no unit)`)
	return parts.join(' · ')
}

async function send() {
	const policy = assignment
	if (!policy || !count || sending) return
	sending = true
	const r = await write({
		domain: 'leads',
		call: () => crm.renewals.issue([...ui.renewalSelected], policy),
		success: summary,
		undoable: false
	})
	sending = false
	if (r) {
		ui.renewalSelected = []
		panel.closeAll()
	}
}
</script>

<Panel kicker="Renewals" title="Issue to agents" sub="{fmt(count)} {count === 1 ? 'unit' : 'units'} selected">
	<div class="form">
		{#if count}
			<p class="small muted">
				Each unit becomes a lead for outbound contact with its owner, carrying the unit, its last
				tenancy and owner details where known.
			</p>
			<AssignmentPicker bind:assignment disabled={sending} noun="leads" id="issue" />
			<div class="actions">
				<button type="button" class="btn" disabled={!assignment || sending} onclick={send}>
					{sending ? 'Issuing…' : `Issue ${fmt(count)} ${count === 1 ? 'unit' : 'units'}`}
				</button>
				<button type="button" class="btn ghost" onclick={() => goto('/crm/inbox')}>Open Inbox</button>
			</div>
		{:else}
			<p class="small muted">Tick units in Assets › Renewals first.</p>
		{/if}
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
