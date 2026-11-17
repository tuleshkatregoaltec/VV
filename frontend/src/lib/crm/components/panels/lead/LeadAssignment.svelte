<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../../api'
import type { LeadDetail } from '../../../api/types'
import { assignChoices, personName, teamName } from '../../../assignment'
import { fullDate } from '../../../format'
import { crmQueries } from '../../../queries'
import { write } from '../../../write'

/**
 * Who handles this lead, its assignment history and, for managers and organization
 * administrators, reassignment or sharing with a team's pool. The server decides who may assign
 * and to whom; the change quotes the revision shown here, so a change someone made meanwhile is
 * refused, not overwritten.
 */
let { lead }: { lead: LeadDetail } = $props()

const scope = createQuery(() => crmQueries.assignmentScope())
const history = createQuery(() => crmQueries.leadAssignments(lead.id))
const canAssign = $derived(scope.data?.capabilities.can_assign ?? false)
// One option per person per team: someone in two of your teams is given to one explicit team.
const choices = $derived(scope.data ? assignChoices(scope.data) : [])
const teams = $derived(scope.data?.teams ?? [])

const REASON: Record<string, string> = {
	created: 'Created',
	import_agent: 'Imported',
	import_rule: 'Routing rule',
	manual: 'Reassigned',
	approved_from_inbox: 'Approved from the Inbox',
	released: 'Shared with the team',
	claimed: 'Taken from the team pool',
	rotation: 'Moved on (no response in time)'
}

let editing = $state(false)
let choice = $state('')
let initial = $state('')
let saving = $state(false)

/** The option for how the lead stands now: its holder in its team, the pool, or nobody. */
function current(): string {
	if (lead.shared && lead.team_id) return `pool:${lead.team_id}`
	if (!lead.assigned_user_id) return ''
	const theirs = choices.filter((c) => c.user_id === lead.assigned_user_id)
	return (theirs.find((c) => c.team_id === lead.team_id) ?? theirs[0])?.key ?? ''
}

function start() {
	initial = current()
	choice = initial
	editing = true
}

async function save() {
	saving = true
	const revision = [{ id: lead.id, assignment_revision: lead.assignment_revision }]
	const pool = choice.startsWith('pool:') ? choice.slice(5) : null
	const picked = choices.find((c) => c.key === choice)
	const r = await write({
		call: () =>
			pool
				? crm.assignment.release(revision, pool)
				: crm.assignment.assign(revision, picked?.user_id ?? null, picked?.team_id ?? null),
		success: pool
			? `Shared with ${teamName(scope.data, pool)}`
			: picked
				? `Assigned to ${personName(scope.data, picked.user_id)}`
				: 'Lead unassigned',
		undoable: false,
		event: 'lead_assigned'
	})
	saving = false
	if (r) editing = false
}

const name = (id: string | null | undefined) =>
	id === 'system' ? 'Automatic' : id ? personName(scope.data, id) : 'Unassigned'
</script>

<section class="sec">
	<h3>
		Handled by
		{#if canAssign && !editing}
			<button type="button" class="link small" onclick={start}>Reassign</button>
		{/if}
	</h3>
	{#if editing}
		<form
			class="row"
			onsubmit={(e) => {
				e.preventDefault()
				save()
			}}
		>
			<select aria-label="Assign to" bind:value={choice} disabled={saving}>
				<option value="">Unassigned (for a manager to assign)</option>
				{#each teams as t (t.id)}
					<option value={`pool:${t.id}`}>Share with {t.name}: first to log contact takes it</option>
				{/each}
				{#each choices as c (c.key)}
					<option value={c.key}>{c.label}</option>
				{/each}
			</select>
			<button type="submit" class="btn sm" disabled={saving || choice === initial}>
				{saving ? 'Saving…' : 'Save'}
			</button>
			<button type="button" class="btn ghost sm" onclick={() => (editing = false)}>Cancel</button>
		</form>
	{:else if lead.shared}
		<div>Waiting in {teamName(scope.data, lead.team_id)}’s shared pool</div>
		<div class="small muted">
			The first agent to log contact (call, WhatsApp, email or meeting) takes it.
		</div>
	{:else}
		<div>{name(lead.assigned_user_id)}</div>
		{#if lead.team_id}
			<div class="small muted">Team: {teamName(scope.data, lead.team_id)}</div>
		{/if}
	{/if}
	{#if history.data?.length}
		<ul class="hist small muted">
			{#each history.data as e (e.id)}
				<li>
					{fullDate(e.created_at.slice(0, 10))} ·{REASON[e.reason] ?? e.reason}: {name(e.previous_user_id)} → {name(
						e.assigned_user_id
					)}{e.actor_user_id !== e.assigned_user_id ? ` · by ${name(e.actor_user_id)}` : ''}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}
	.row select {
		flex: 1;
		min-width: 0;
	}
	.link {
		margin-left: 0.5rem;
		padding: 0;
		border: 0;
		background: none;
		color: var(--accent);
		cursor: pointer;
	}
	.hist {
		list-style: none;
		margin: 0.4rem 0 0;
		padding: 0;
		display: grid;
		gap: 0.2rem;
	}
</style>
