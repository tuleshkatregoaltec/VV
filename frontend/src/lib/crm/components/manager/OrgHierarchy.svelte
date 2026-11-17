<script lang="ts">
/**
 * Organisation hierarchy: organisation → owner and administrators → teams (led by their supervisors)
 * → agents, plus everyone not yet in a team. People without a team can be placed straight from the tree.
 */
import { createQuery } from '@tanstack/svelte-query'
import Building from 'lucide-svelte/icons/building-2'
import ChevronDown from 'lucide-svelte/icons/chevron-down'
import ChevronRight from 'lucide-svelte/icons/chevron-right'
import Pencil from 'lucide-svelte/icons/pencil'
import Shield from 'lucide-svelte/icons/shield'
import UserPlus from 'lucide-svelte/icons/user-plus'
import UsersRound from 'lucide-svelte/icons/users-round'
import type { TeamMemberInput, TeamResponse } from '$lib/api/generated/hey-api/types.gen'
import { setTeamMembers } from '$lib/api/organization'
import { currentUser } from '$lib/stores/user.svelte'
import { crmQueries } from '../../queries'
import { write } from '../../write'
import QueryView from '../ui/QueryView.svelte'

let { onEditTeam }: { onEditTeam: (teamId: string) => void } = $props()

const teams = createQuery(() => crmQueries.teams())
let collapsed = $state<Record<string, boolean>>({})
let busy = $state(false)

function initials(name: string) {
	return name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0])
		.join('')
		.toUpperCase()
}

async function addToTeam(team: TeamResponse, userId: string, role: TeamMemberInput['role']) {
	busy = true
	const members: TeamMemberInput[] = [
		...team.members.map((member) => ({ user_id: member.user_id, role: member.role })),
		{ user_id: userId, role }
	]
	await write({
		call: () => setTeamMembers(team.id, members),
		success: `Added to ${team.name}`,
		undoable: false
	})
	busy = false
}
</script>

<QueryView query={teams} rows={4}>
	{#snippet children(data)}
		{@const leaders = data.people.filter((p) => p.role === 'owner' || p.organization_admin)}
		{@const inTeam = new Set(data.teams.flatMap((t) => t.members.map((m) => m.user_id)))}
		{@const unplaced = data.people.filter((p) => !inTeam.has(p.user_id) && p.role !== 'owner' && !p.organization_admin)}
		<div class="legend small muted">
			<span><Shield size={13} /> Supervisor: runs the team, imports and issues leads</span>
			<span><span class="dot"></span> Agent: works the leads issued to them</span>
		</div>
		<div class="chart" role="tree" aria-label="Organisation hierarchy">
			<div class="node root" role="treeitem" aria-selected="false" aria-expanded="true">
				<span class="icon"><Building size={18} /></span>
				<div>
					<strong>{currentUser.data?.organization_name ?? 'Organisation'}</strong>
					<small>{data.people.length} people · {data.teams.length} {data.teams.length === 1 ? 'team' : 'teams'}</small>
				</div>
			</div>
			<div class="stem"></div>
			<div class="node leaders">
				<small class="kicker">Owner &amp; administrators</small>
				<ul class="people">
					{#each leaders as person (person.user_id)}
						<li>
							<span class="avatar sm">{initials(person.name || person.email)}</span>
							<span class="who">{person.name || person.email}</span>
							<span class="badge">{person.role === 'owner' ? 'Owner' : 'Admin'}</span>
						</li>
					{/each}
				</ul>
			</div>

			<ul class="branches" role="group">
				{#each data.teams as team (team.id)}
					{@const supervisors = team.members.filter((m) => m.role === 'supervisor')}
					{@const agents = team.members.filter((m) => m.role === 'agent')}
					{@const open = !collapsed[team.id]}
					<li class="branch" role="treeitem" aria-selected="false" aria-expanded={open}>
						<div class="node team">
							<header>
								<button
									type="button"
									class="toggle"
									aria-label="{open ? 'Collapse' : 'Expand'} {team.name}"
									onclick={() => (collapsed[team.id] = open)}
								>
									{#if open}<ChevronDown size={16} />{:else}<ChevronRight size={16} />{/if}
								</button>
								<UsersRound size={16} />
								<strong>{team.name}</strong>
								<button type="button" class="btn ghost sm edit" aria-label="Edit {team.name}" onclick={() => onEditTeam(team.id)}>
									<Pencil size={13} />
								</button>
							</header>
							{#if supervisors.length}
								{#each supervisors as s (s.user_id)}
									<div class="lead"><Shield size={13} /><span class="who">{s.name}</span></div>
								{/each}
							{:else}
								<div class="lead missing">No supervisor yet</div>
							{/if}
							<small class="muted">{agents.length} {agents.length === 1 ? 'agent' : 'agents'}</small>
						</div>
						{#if open}
							<ul class="agents" role="group">
								{#each agents as agent (agent.user_id)}
									<li role="treeitem" aria-selected="false">
										<span class="avatar sm">{initials(agent.name || agent.email)}</span>
										<span class="who">{agent.name}</span>
									</li>
								{:else}
									<li class="muted small empty">No agents</li>
								{/each}
							</ul>
						{/if}
					</li>
				{/each}
				{#if unplaced.length || !data.teams.length}
					<li class="branch" role="treeitem" aria-selected="false" aria-expanded="true">
						<div class="node team unplaced">
							<header><UserPlus size={16} /><strong>Not in a team</strong></header>
							<small class="muted">{unplaced.length} {unplaced.length === 1 ? 'person' : 'people'}</small>
						</div>
						<ul class="agents" role="group">
							{#each unplaced as person (person.user_id)}
								<li role="treeitem" aria-selected="false" class="placeable">
									<span class="avatar sm">{initials(person.name || person.email)}</span>
									<span class="who">{person.name || person.email}</span>
									{#if data.teams.length}
										<select
											aria-label="Add {person.name || person.email} to a team"
											disabled={busy}
											value=""
											onchange={(event) => {
												const [teamId, role] = event.currentTarget.value.split('|')
												const team = data.teams.find((t) => t.id === teamId)
												if (team) addToTeam(team, person.user_id, role as TeamMemberInput['role'])
											}}
										>
											<option value="">Add to…</option>
											{#each data.teams as team (team.id)}
												<option value="{team.id}|agent">{team.name} — agent</option>
												<option value="{team.id}|supervisor">{team.name} — supervisor</option>
											{/each}
										</select>
									{/if}
								</li>
							{:else}
								<li class="muted small empty">Create a team in the Teams tab to start building the hierarchy.</li>
							{/each}
						</ul>
					</li>
				{/if}
			</ul>
		</div>
	{/snippet}
</QueryView>

<style>
	.legend {
		display: flex;
		flex-wrap: wrap;
		gap: 18px;
		margin-bottom: 16px;
	}
	.legend span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--accent-fill);
	}
	.chart {
		--gap: 22px;
		display: flex;
		flex-direction: column;
		align-items: center;
		overflow-x: auto;
		padding: 8px 4px 32px;
	}
	.node {
		background: var(--card);
		border: 1px solid var(--sep);
		border-radius: 12px;
		padding: 12px 14px;
		box-shadow: var(--shadow);
	}
	.node small {
		display: block;
		font-size: 12px;
		color: var(--text3);
	}
	.root {
		display: flex;
		align-items: center;
		gap: 10px;
		border-color: var(--accent-fill);
	}
	.root .icon {
		display: grid;
		place-items: center;
		width: 34px;
		height: 34px;
		border-radius: 9px;
		background: var(--sunk);
		color: var(--accent);
	}
	.stem {
		width: 1px;
		height: var(--gap);
		background: var(--sep-strong);
	}
	.leaders {
		min-width: 240px;
		background: var(--sunk);
	}
	.kicker {
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-weight: 600;
		margin-bottom: 6px;
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
	}
	.people li,
	.agents li {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 4px 0;
		font-size: 13px;
	}
	.who {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.avatar.sm {
		width: 24px;
		height: 24px;
		font-size: 10px;
	}
	.badge {
		margin-left: auto;
		font-size: 11px;
		padding: 1px 7px;
		border-radius: 999px;
		background: var(--blue-bg);
		color: var(--blue);
	}

	/* Org-chart connectors: a stem down from the leaders box, a rail across, a drop into each team. */
	.branches {
		display: flex;
		justify-content: center;
		position: relative;
		padding-top: var(--gap);
	}
	.branches::before {
		content: '';
		position: absolute;
		top: 0;
		left: 50%;
		height: var(--gap);
		border-left: 1px solid var(--sep-strong);
	}
	.branch {
		position: relative;
		padding: var(--gap) 10px 0;
		min-width: 220px;
		max-width: 260px;
	}
	.branch::before {
		content: '';
		position: absolute;
		top: 0;
		left: 50%;
		height: var(--gap);
		border-left: 1px solid var(--sep-strong);
	}
	.branch::after {
		content: '';
		position: absolute;
		top: 0;
		left: 0;
		right: 0;
		border-top: 1px solid var(--sep-strong);
	}
	.branch:first-child::after {
		left: 50%;
	}
	.branch:last-child::after {
		right: 50%;
	}
	.branch:only-child::after {
		display: none;
	}
	.team header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 6px;
	}
	.team header strong {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.toggle {
		display: grid;
		place-items: center;
		padding: 0;
		border: 0;
		background: none;
		color: var(--text3);
		cursor: pointer;
	}
	.edit {
		padding: 2px 6px;
	}
	.lead {
		display: flex;
		align-items: center;
		gap: 6px;
		font-size: 13px;
		font-weight: 600;
		color: var(--accent);
	}
	.lead.missing {
		font-weight: 500;
		color: var(--amber);
	}
	.unplaced {
		border-style: dashed;
		background: var(--sunk);
	}
	.agents {
		margin: 0 0 0 18px;
		border-left: 1px solid var(--sep-strong);
	}
	.agents li {
		position: relative;
		padding-left: 14px;
		margin-top: 6px;
	}
	.agents li::before {
		content: '';
		position: absolute;
		left: 0;
		top: 50%;
		width: 10px;
		border-top: 1px solid var(--sep-strong);
	}
	.agents li.empty {
		padding-top: 4px;
	}
	.placeable {
		flex-wrap: wrap;
	}
	.placeable select {
		margin-left: auto;
		max-width: 130px;
		font-size: 12px;
	}

	@media (max-width: 720px) {
		.branches {
			flex-direction: column;
			align-items: stretch;
			width: 100%;
		}
		.branches::before,
		.branch::after {
			display: none;
		}
		.branch {
			max-width: none;
		}
	}
</style>
