<script lang="ts">
/**
 * "Who handles the new leads": the one routing step wherever leads are issued (a Leads import,
 * Renewals). Someone who may assign picks one agent, the routing rules, the team's shared pool
 * or nobody yet, and which of their teams owns what nobody receives; anyone else's leads go to
 * themselves. `assignment` is the policy to send, or null while the choice is incomplete.
 */
import { createQuery } from '@tanstack/svelte-query'
import type { ImportAssignment } from '../../api/types'
import { assignChoices } from '../../assignment'
import { fmt } from '../../format'
import { crmQueries } from '../../queries'
import Seg from './Seg.svelte'

let {
	assignment = $bindable(null),
	disabled = false,
	noun = 'leads',
	id = 'assign'
}: {
	assignment?: ImportAssignment | null
	disabled?: boolean
	/** What is being issued, e.g. "leads" or "units". */
	noun?: string
	/** Prefix for the form controls' ids, unique per page. */
	id?: string
} = $props()

type Mode = ImportAssignment['mode']
let mode = $state<Mode>('agent')
/** "user|team": one option per person per team, so a person in two teams goes to one of them. */
let assignee = $state('')
let teamChoice = $state('')

const scope = createQuery(() => crmQueries.assignmentScope())
const canDistribute = $derived(scope.data?.capabilities.can_assign ?? false)
const rules = createQuery(() => ({ ...crmQueries.routingRules(), enabled: canDistribute }))
const choices = $derived(scope.data ? assignChoices(scope.data) : [])
const managedTeams = $derived(scope.data?.teams ?? [])
const isAdmin = $derived(scope.data?.capabilities.organization_admin ?? false)
/** A manager of one team never chooses; otherwise "team" needs one, and a manager must say. */
const onlyTeam = $derived(managedTeams.length === 1 ? managedTeams[0].id : '')
const teamFor = $derived(onlyTeam || teamChoice)
const teamMissing = $derived(
	!teamFor && (mode === 'team' || (!isAdmin && (mode === 'rules' || mode === 'unassigned')))
)
const enabledRules = $derived((rules.data ?? []).filter((r) => r.enabled).length)

const chosen = $derived<ImportAssignment | null>(
	!scope.data
		? null
		: !canDistribute
			? { mode: 'self' }
			: mode === 'agent'
				? assignee
					? {
							mode,
							assignee_user_id: assignee.split('|')[0],
							team_id: assignee.split('|')[1]
						}
					: null
				: teamMissing
					? null
					: mode === 'rules'
						? enabledRules
							? { mode, team_id: teamFor || undefined }
							: null
						: { mode, team_id: teamFor || undefined }
)
$effect(() => {
	assignment = chosen
})
</script>

{#if scope.data && !canDistribute}
	<div class="notice" role="status">These {noun} will be assigned to you.</div>
{:else if scope.data}
	<div class="fld">
		<span class="fl">Who handles the new {noun}</span>
		<Seg
			label="Who handles the new {noun}"
			items={[
				{ id: 'agent', label: 'One agent' },
				{ id: 'rules', label: 'Routing rules' },
				{ id: 'team', label: 'Share with team' },
				{ id: 'unassigned', label: 'Leave unassigned' }
			]}
			value={mode}
			onselect={(m) => (mode = m)}
		/>
	</div>
	{#if mode === 'agent'}
		<div class="fld">
			<label for="{id}-agent">Agent</label>
			<select id="{id}-agent" bind:value={assignee} {disabled}>
				<option value="">{choices.length ? 'Choose an agent' : 'No agents in your teams yet'}</option>
				{#each choices as c (c.key)}
					<option value={c.key}>{c.label}</option>
				{/each}
			</select>
		</div>
	{:else if mode === 'rules'}
		<div class="small muted">
			{#if rules.isPending}
				Loading routing rules…
			{:else if enabledRules}
				{fmt(enabledRules)} enabled {enabledRules === 1 ? 'rule' : 'rules'}, first match wins.
				{noun[0].toUpperCase() + noun.slice(1)} no rule matches stay unassigned in the Inbox.
				<a href="/crm/organization?tab=routing">Review rules</a>
			{:else}
				There are no enabled routing rules for your teams.
				<a href="/crm/organization?tab=routing">Set up routing rules</a>
			{/if}
		</div>
	{:else if mode === 'team'}
		<div class="small muted">
			Every agent in the team sees the new {noun}. The first to log contact (call, WhatsApp, email
			or meeting) takes each one, and it disappears for the others.
		</div>
	{:else}
		<div class="small muted">The new {noun} wait in the Inbox until a manager assigns them.</div>
	{/if}
	{#if mode !== 'agent' && managedTeams.length > 1}
		<div class="fld">
			<label for="{id}-team">{mode === 'team' ? 'Team' : 'Team that owns leads nobody receives'}</label>
			<select id="{id}-team" bind:value={teamChoice} {disabled}>
				<option value="">
					{mode === 'team' || !isAdmin ? 'Choose a team' : 'No team (administrators only)'}
				</option>
				{#each managedTeams as t (t.id)}
					<option value={t.id}>{t.name}</option>
				{/each}
			</select>
		</div>
	{/if}
{/if}
