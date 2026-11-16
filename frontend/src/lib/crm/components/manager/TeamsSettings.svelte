<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/plus'
import Search from 'lucide-svelte/icons/search'
import Shield from 'lucide-svelte/icons/shield'
import Trash from 'lucide-svelte/icons/trash-2'
import UserRound from 'lucide-svelte/icons/user-round'
import UsersRound from 'lucide-svelte/icons/users-round'
import type { TeamMemberInput, TeamResponse } from '$lib/api/generated/hey-api/types.gen'
import { createTeam, deleteTeam, setOrganizationAdmin, setTeamMembers } from '$lib/api/organization'
import { crmQueries } from '../../queries'
import { write } from '../../write'
import QueryView from '../ui/QueryView.svelte'
import Tabs from '../ui/Tabs.svelte'

/** Team to open first, e.g. when "Edit" is pressed on a team in the hierarchy tree. */
let { teamId = '' }: { teamId?: string } = $props()

const teams = createQuery(() => crmQueries.teams())
const me = createQuery(() => crmQueries.me())
const tabs = [
	{ id: 'teams', label: 'Teams' },
	{ id: 'members', label: 'Members' }
] as const

let tab = $state<(typeof tabs)[number]['id']>('teams')
let selectedTeamId = $state('')
$effect(() => {
	if (teamId) {
		selectedTeamId = teamId
		tab = 'teams'
	}
})
let teamSearch = $state('')
let memberSearch = $state('')
let newTeam = $state('')
let creatingTeam = $state(false)
let adding = $state<Record<string, { user_id: string; role: TeamMemberInput['role'] }>>({})
let confirming = $state<string | null>(null)
let busy = $state(false)

async function run<R>(call: () => Promise<R>, success: string) {
	busy = true
	const result = await write({ call, success, undoable: false })
	busy = false
	return result
}

const membersOf = (team: TeamResponse): TeamMemberInput[] =>
	team.members.map((member) => ({ user_id: member.user_id, role: member.role }))

async function add(team: TeamResponse) {
	const pick = adding[team.id]
	if (!pick?.user_id) return
	const result = await run(
		() => setTeamMembers(team.id, [...membersOf(team), pick]),
		`Added to ${team.name}`
	)
	if (result) adding[team.id] = { user_id: '', role: 'agent' }
}

function change(team: TeamResponse, userId: string, role: TeamMemberInput['role'] | null) {
	const members = membersOf(team)
		.filter((member) => role !== null || member.user_id !== userId)
		.map((member) => (member.user_id === userId && role ? { ...member, role } : member))
	return run(() => setTeamMembers(team.id, members), `${team.name} updated`)
}

async function create() {
	const name = newTeam.trim()
	if (!name) return
	if (await run(() => createTeam(name), `Team ${name} created`)) {
		newTeam = ''
		creatingTeam = false
	}
}

function initials(name: string) {
	return name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0])
		.join('')
		.toUpperCase()
}
</script>

<section class="page">
	<QueryView query={teams} rows={3}>
		{#snippet children(data)}
			{@const team = data.teams.find((item) => item.id === selectedTeamId) ?? data.teams[0]}
			<div class="team-toolbar">
				<Tabs items={[...tabs]} value={tab} onselect={(id) => (tab = id)} label="Teams and members" />
				<button
					type="button"
					class="btn sm"
					aria-expanded={creatingTeam}
					aria-controls="create-team-form"
					onclick={() => (creatingTeam = !creatingTeam)}
				><Plus size={16} /> Create team</button>
			</div>
			{#if creatingTeam}
				<form
					id="create-team-form"
					class="create-form"
				onsubmit={(event) => {
						event.preventDefault()
						create()
					}}
				>
					<label class="sr-only" for="new-team">Team name</label>
					<input id="new-team" maxlength="120" placeholder="Team name" bind:value={newTeam} />
					<button type="submit" class="btn sm" disabled={busy || !newTeam.trim()}><Plus size={15} /> Create</button>
					<button type="button" class="btn ghost sm" onclick={() => (creatingTeam = false)}>Cancel</button>
				</form>
			{/if}
			{#if tab === 'teams'}
				<div class="team-layout">
					<aside class="team-picker" aria-label="Teams">
						<h3>Teams ({data.teams.length})</h3>
						<label class="search-control">
							<Search size={17} aria-hidden="true" />
							<span class="sr-only">Search teams</span>
							<input type="search" bind:value={teamSearch} placeholder="Search teams…" />
						</label>
						<div class="team-options">
							{#each data.teams.filter((team) => team.name.toLocaleLowerCase().includes(teamSearch.trim().toLocaleLowerCase())) as team (team.id)}
								<button
									type="button"
									class="team-option"
									class:selected={selectedTeamId === team.id || (!selectedTeamId && data.teams[0]?.id === team.id)}
									aria-current={selectedTeamId === team.id || (!selectedTeamId && data.teams[0]?.id === team.id) ? 'true' : undefined}
								onclick={() => {
										selectedTeamId = team.id
										confirming = null
									}}
								>
									<UsersRound size={17} aria-hidden="true" />
									<span>{team.name}</span>
									<small>{team.members.length} people</small>
								</button>
							{:else}
								<p class="small muted">{data.teams.length ? 'No teams match your search.' : 'Create a team to get started.'}</p>
							{/each}
						</div>
					</aside>

					{#if team}
						{@const pick = adding[team.id] ?? { user_id: '', role: 'agent' as const }}
						{@const others = data.people.filter((person) => !team.members.some((member) => member.user_id === person.user_id))}
						<section class="team-detail" aria-labelledby="selected-team-title">
							<header class="detail-header">
								<div class="team-title">
									<span class="team-icon" aria-hidden="true"><UsersRound size={23} /></span>
									<h3 id="selected-team-title">{team.name}</h3>
									<span class="count">{team.members.length} {team.members.length === 1 ? 'member' : 'members'}</span>
								</div>
								{#if confirming === team.id}
									<div class="actions">
										<span class="small muted">Delete this team?</span>
										<button
											type="button"
											class="btn danger sm"
											disabled={busy}
											onclick={async () => {
												await run(() => deleteTeam(team.id), `Team ${team.name} deleted`)
												confirming = null
												selectedTeamId = ''
											}}
										>Delete</button>
										<button type="button" class="btn ghost sm" onclick={() => (confirming = null)}>Cancel</button>
									</div>
								{:else}
									<button type="button" class="btn ghost sm" aria-label="Delete {team.name}" onclick={() => (confirming = team.id)}>
										<Trash size={15} /> Delete team
									</button>
								{/if}
							</header>

							<div class="role-notes">
								<span class="role-badge supervisor"><Shield size={16} /> {team.members.filter((member) => member.role === 'supervisor').length} Supervisors</span>
								<span class="role-badge agent"><UserRound size={16} /> {team.members.filter((member) => member.role === 'agent').length} Agents</span>
								<p><b>Supervisor:</b> manages the team, imports leads and assigns them.<br /><b>Agent:</b> receives leads and works on them.</p>
							</div>

							<div class="members-head">
								<h4>Members</h4>
								{#if others.length}
									<div class="add-member">
										<select aria-label="Person to add to {team.name}" value={pick.user_id} disabled={busy} onchange={(event) => (adding[team.id] = { ...pick, user_id: event.currentTarget.value })}>
											<option value="">Choose a person…</option>
											{#each others as person (person.user_id)}<option value={person.user_id}>{person.name}</option>{/each}
										</select>
										<select aria-label="Role for person in {team.name}" value={pick.role} disabled={busy} onchange={(event) => (adding[team.id] = { ...pick, role: event.currentTarget.value as TeamMemberInput['role'] })}>
											<option value="agent">Agent</option><option value="supervisor">Supervisor</option>
										</select>
										<button type="button" class="btn sm" disabled={busy || !pick.user_id} onclick={() => add(team)}><Plus size={15} /> Add member</button>
									</div>
								{/if}
							</div>

							{#if team.members.length}
								<div class="tblwrap">
									<table class="tbl">
										<caption class="sr-only">Members of {team.name}</caption>
										<thead><tr><th scope="col">Name</th><th scope="col">Role</th><th scope="col" class="action">Actions</th></tr></thead>
										<tbody>
											{#each team.members as member (member.user_id)}
												<tr>
													<th scope="row" class="person"><span class="avatar">{initials(member.name || 'Member')}</span><span>{member.name}</span></th>
													<td><select aria-label="Role of {member.name} in {team.name}" value={member.role} disabled={busy} onchange={(event) => change(team, member.user_id, event.currentTarget.value as TeamMemberInput['role'])}><option value="agent">Agent</option><option value="supervisor">Supervisor</option></select></td>
													<td class="action"><button type="button" class="btn ghost sm" disabled={busy} aria-label="Remove {member.name} from {team.name}" onclick={() => change(team, member.user_id, null)}><Trash size={15} /></button></td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{:else}
								<p class="empty small muted">Add at least one person. Until then, no lead can go to this team.</p>
							{/if}
						</section>
					{/if}
				</div>
			{:else}
				<div class="members-view">
					<label class="search-control member-search">
						<Search size={17} aria-hidden="true" />
						<span class="sr-only">Search members</span>
						<input type="search" bind:value={memberSearch} placeholder="Search members…" />
					</label>
					<div class="tblwrap">
						<table class="tbl">
							<caption class="sr-only">Organization members and their team access</caption>
							<thead><tr><th scope="col">Name</th><th scope="col">Teams</th><th scope="col">Organization access</th></tr></thead>
							<tbody>
								{#each data.people.filter((person) => `${person.name} ${person.email}`.toLocaleLowerCase().includes(memberSearch.trim().toLocaleLowerCase())) as person (person.user_id)}
									{@const memberTeams = data.teams.filter((team) => team.members.some((member) => member.user_id === person.user_id))}
									<tr>
										<th scope="row" class="person"><span class="avatar">{initials(person.name || 'Member')}</span><span>{person.name}<small>{person.email}</small></span></th>
										<td>{memberTeams.length ? memberTeams.map((team) => team.name).join(', ') : 'No team'}</td>
										<td>
											{#if person.role === 'owner'}
												<span class="access"><Shield size={15} /> Owner</span>
											{:else if me.data?.is_owner}
												<label class="admin-toggle"><input type="checkbox" checked={person.organization_admin} disabled={busy} onchange={(event) => run(() => setOrganizationAdmin(person.user_id, event.currentTarget.checked), event.currentTarget.checked ? `${person.name} is now an organization admin` : `${person.name} is no longer an organization admin`)} /> Organization admin</label>
											{:else}
												{person.organization_admin ? 'Organization admin' : 'Member'}
											{/if}
										</td>
									</tr>
								{:else}
									<tr><td colspan="3" class="empty small muted">No members match your search.</td></tr>
								{/each}
							</tbody>
						</table>
					</div>
				</div>
			{/if}
		{/snippet}
	</QueryView>
</section>

<style>
	.page { display: grid; gap: 1rem; }
	.team-toolbar, .team-title, .actions, .role-notes, .members-head, .add-member, .person, .access, .admin-toggle { display: flex; align-items: center; }
	.team-toolbar { gap: 0.75rem; }
	.team-toolbar :global(.tabs) { flex: 1; min-width: 0; }
	.team-picker h3, .team-title h3, .members-head h4 { margin: 0; }
	.team-icon { display: grid; place-items: center; flex: none; border-radius: 0.75rem; background: var(--sel); color: var(--accent); }
	.team-icon { width: 2.7rem; height: 2.7rem; }
	.create-form { display: flex; flex-wrap: wrap; gap: 0.5rem; padding: 0.75rem; border: 1px solid var(--sep); border-radius: 0.7rem; background: var(--sunk); }
	.create-form input { flex: 1; min-width: 12rem; }
	.team-layout { display: grid; grid-template-columns: minmax(13rem, 22rem) minmax(0, 1fr); gap: 1rem; }
	.team-picker, .team-detail, .members-view { min-width: 0; padding: 1rem; border: 1px solid var(--sep); border-radius: 0.8rem; background: var(--card); }
	.team-picker { display: grid; align-content: start; gap: 0.8rem; }
	.search-control { display: flex; align-items: center; gap: 0.5rem; min-height: 2.5rem; padding: 0 0.65rem; border: 1px solid var(--sep-strong); border-radius: 0.55rem; background: var(--card); color: var(--text3); }
	.search-control input { width: 100%; min-width: 0; padding: 0; border: 0; outline: 0; background: transparent; }
	.team-options { display: grid; gap: 0.35rem; }
	.team-option { display: flex; align-items: center; gap: 0.55rem; width: 100%; padding: 0.65rem; border: 1px solid transparent; border-radius: 0.55rem; text-align: left; color: var(--text); transition: background-color 180ms, border-color 180ms; }
	.team-option:hover { background: var(--sunk); }
	.team-option.selected { border-color: var(--accent); background: var(--sel); }
	.team-option span { flex: 1; min-width: 0; font-weight: 600; }
	.team-option small, .person small { display: block; color: var(--text3); font-size: 0.75rem; }
	.team-detail { display: grid; gap: 1rem; }
	.detail-header, .members-head { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; flex-wrap: wrap; }
	.team-title { gap: 0.7rem; min-width: 0; }
	.team-title h3 { font-size: 1.2rem; }
	.count { padding: 0.25rem 0.6rem; border-radius: 999px; background: var(--sel); color: var(--text2); font-size: 0.78rem; white-space: nowrap; }
	.actions { gap: 0.5rem; flex-wrap: wrap; }
	.role-notes { gap: 0.55rem; flex-wrap: wrap; padding: 0.75rem; border-block: 1px solid var(--sep); }
	.role-notes p { flex: 1; min-width: 15rem; margin: 0 0 0 auto; color: var(--text2); font-size: 0.8rem; line-height: 1.6; }
	.role-badge, .access { gap: 0.4rem; padding: 0.45rem 0.6rem; border: 1px solid var(--sep); border-radius: 0.55rem; font-size: 0.8rem; white-space: nowrap; }
	.role-badge.supervisor { color: var(--accent); background: var(--sel); }
	.role-badge.agent { color: var(--green, var(--accent)); background: var(--sunk); }
	.members-head h4 { font-size: 1rem; }
	.add-member { gap: 0.45rem; flex-wrap: wrap; }
	.add-member select:first-child { min-width: 10rem; }
	.add-member select:nth-child(2) { min-width: 8rem; }
	.tblwrap { overflow-x: auto; border: 1px solid var(--sep); border-radius: 0.6rem; }
	.tbl { width: 100%; border-collapse: collapse; }
	.tbl th, .tbl td { padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--sep); text-align: left; }
	.tbl thead { background: var(--sunk); color: var(--text2); font-size: 0.78rem; }
	.tbl tbody tr:last-child > * { border-bottom: 0; }
	.tbl .person { gap: 0.55rem; min-width: 10rem; color: var(--text); }
	.avatar { display: inline-grid; place-items: center; flex: none; width: 2rem; height: 2rem; border-radius: 50%; background: var(--sel); color: var(--accent); font-size: 0.72rem; font-weight: 700; }
	.tbl select { min-width: 9rem; }
	.tbl .action { width: 1%; text-align: right; white-space: nowrap; }
	.empty { padding: 1rem; text-align: center; }
	.members-view { display: grid; gap: 0.8rem; }
	.member-search { max-width: 28rem; }
	.access { display: inline-flex; }
	.admin-toggle { gap: 0.4rem; cursor: pointer; }
	@media (max-width: 760px) {
		.team-toolbar { align-items: center; }
		.team-layout { grid-template-columns: 1fr; }
		.team-options { grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); }
		.role-notes p { min-width: 100%; margin: 0; }
	}
</style>
