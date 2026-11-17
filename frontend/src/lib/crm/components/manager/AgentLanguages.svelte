<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import Languages from 'lucide-svelte/icons/languages'
import Search from 'lucide-svelte/icons/search'
import UsersRound from 'lucide-svelte/icons/users-round'
import { crm } from '../../api'
import { crmKeys, crmQueries } from '../../queries'
import { write } from '../../write'
import QueryView from '../ui/QueryView.svelte'

/**
 * The languages each team member speaks, as their manager records them. Routing rules set to
 * "speakers only" use these; nothing is inferred from a name or nationality. A manager edits the
 * people in the teams they supervise; an administrator everyone.
 */
const scope = createQuery(() => crmQueries.assignmentScope())
const queryClient = useQueryClient()
let editing = $state<string | null>(null)
let text = $state('')
let busy = $state(false)
let teamId = $state('')
let search = $state('')
const searchTerm = $derived(search.trim().toLocaleLowerCase())

const split = (value: string) =>
	value
		.split(/[,;\n]/)
		.map((s) => s.trim())
		.filter(Boolean)

function matchesSearch(value: string | null | undefined) {
	return !searchTerm || (value ?? '').toLocaleLowerCase().includes(searchTerm)
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

function start(userId: string, languages: string[]) {
	editing = userId
	text = languages.join(', ')
}

async function save(userId: string, name: string) {
	busy = true
	const r = await write({
		call: () => crm.assignment.setLanguages(userId, split(text)),
		success: ({ data }) =>
			data.languages.length
				? name + ' speaks ' + data.languages.join(', ')
				: 'No languages recorded for ' + name,
		undoable: false
	})
	busy = false
	if (r) {
		editing = null
		await queryClient.invalidateQueries({ queryKey: crmKeys.assignmentScope() })
	}
}
</script>

<section class="card languages" aria-labelledby="languages-h">
	<header class="languages-header">
		<span class="header-icon" aria-hidden="true"><Languages size={25} /></span>
		<div>
			<h2 id="languages-h">Languages your agents speak</h2>
			<p class="small muted">
				Used only by rules set to “only people who speak the lead’s language”. Record what each person tells
				you; nothing is guessed from names.
			</p>
		</div>
	</header>

	<QueryView query={scope} rows={2}>
		{#snippet children(data)}
			<div class="filters">
				<label>
					<span>Team</span>
					<select bind:value={teamId}>
						<option value="">All teams</option>
						{#each data.teams as team (team.id)}
							<option value={team.id}>{team.name}</option>
						{/each}
					</select>
				</label>
				<label class="people-search">
					<span>Search</span>
					<div class="search-control">
						<Search size={18} aria-hidden="true" />
						<input type="search" bind:value={search} placeholder="Search people…" />
					</div>
				</label>
			</div>

			<div class="team-list">
				{#each data.teams.filter((team) => (teamId === '' || team.id === teamId) && team.members.some((member) => matchesSearch(member.name))) as team (team.id)}
					<section class="team">
						<header class="team-header">
							<div class="team-name">
								<UsersRound size={21} aria-hidden="true" />
								<h3>{team.name}</h3>
								<span class="recorded">
									{team.members.filter((member) => member.languages?.length).length} of {team.members.length} recorded
								</span>
							</div>
						</header>

						<div class="tblwrap">
							<table class="tbl">
								<caption class="sr-only">{team.name}: agent languages</caption>
								<thead>
									<tr>
										<th scope="col">Person</th>
										<th scope="col">Languages</th>
										<th scope="col" class="action">Action</th>
									</tr>
								</thead>
								<tbody>
									{#each team.members.filter((member) => matchesSearch(member.name)) as member (member.user_id)}
										<tr>
											<th scope="row" class="person">
												<span class="avatar">{initials(member.name || 'Former member')}</span>
												{member.name || 'Former member'}
											</th>
											<td data-label="Languages">
												{#if editing === member.user_id}
													<form
														class="edit-form"
														onsubmit={(event) => {
															event.preventDefault()
															save(member.user_id, member.name)
														}}
													>
														<input
															aria-label={'Languages ' + member.name + ' speaks, separated by commas'}
															placeholder="e.g. Hindi, English"
															bind:value={text}
															disabled={busy}
														/>
														<button type="submit" class="btn sm" disabled={busy}>{busy ? 'Saving…' : 'Save'}</button>
														<button type="button" class="btn ghost sm" onclick={() => (editing = null)}>Cancel</button>
													</form>
												{:else}
													<span class:missing={!member.languages?.length}>
														{member.languages?.length ? member.languages.join(', ') : 'No languages recorded'}
													</span>
												{/if}
											</td>
											<td class="action" data-label="Action">
												{#if editing !== member.user_id}
													<button
														type="button"
														class="btn ghost sm"
														aria-label={'Edit languages for ' + member.name}
														onclick={() => start(member.user_id, member.languages ?? [])}
													>
														Edit
													</button>
												{/if}
											</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					</section>
				{:else}
					<p class="empty small muted">{data.teams.length ? 'No people match your filters.' : 'You don’t manage a team yet.'}</p>
				{/each}
			</div>
		{/snippet}
	</QueryView>
</section>

<style>
	.languages {
		display: grid;
		gap: 0;
		padding: 0;
		overflow: hidden;
	}
	.languages-header {
		display: flex;
		align-items: center;
		gap: 13px;
		padding: 20px;
		border-bottom: 1px solid var(--sep);
	}
	.header-icon {
		display: grid;
		place-items: center;
		width: 46px;
		height: 46px;
		border-radius: 50%;
		background: var(--sel);
		color: var(--accent);
	}
	.languages h2,
	.team h3 {
		margin: 0;
	}
	.languages h2 {
		font-size: 21px;
	}
	.languages p {
		margin: 3px 0 0;
	}
	.filters {
		display: flex;
		gap: 18px;
		align-items: end;
		padding: 13px 20px;
		border-bottom: 1px solid var(--sep);
		background: var(--sunk);
	}
	.filters label {
		display: grid;
		gap: 5px;
		min-width: 260px;
		font-size: 12px;
		font-weight: 600;
		color: var(--text2);
	}
	.filters .people-search {
		flex: 1;
	}
	.filters select,
	.search-control {
		min-height: 38px;
		width: 100%;
	}
	.search-control {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 0 10px;
		border: 1px solid var(--sep-strong);
		border-radius: 8px;
		background: var(--card);
		color: var(--text3);
	}
	.search-control input {
		width: 100%;
		padding: 0;
		border: 0;
		background: transparent;
	}
	.team-list {
		display: grid;
		gap: 16px;
		padding: 12px 20px 20px;
	}
	.team {
		border: 1px solid var(--sep);
		border-radius: 12px;
		overflow: hidden;
	}
	.team-header {
		padding: 11px 16px;
		background: var(--sunk);
	}
	.team-name {
		display: flex;
		align-items: center;
		gap: 9px;
	}
	.team-name h3 {
		font-size: 17px;
	}
	.recorded {
		display: inline-flex;
		align-items: center;
		border-radius: 999px;
		background: var(--sel);
		color: var(--text2);
		font-size: 12px;
		font-weight: 600;
		padding: 4px 9px;
		white-space: nowrap;
	}
	.tbl th,
	.tbl td {
		padding: 9px 16px;
	}
	.person {
		display: flex;
		align-items: center;
		gap: 9px;
		color: var(--text);
	}
	.avatar {
		display: inline-grid;
		place-items: center;
		width: 29px;
		height: 29px;
		border-radius: 50%;
		background: var(--sel);
		color: var(--accent);
		font-size: 11px;
		font-weight: 700;
	}
	.missing {
		color: var(--text2);
	}
	.action {
		width: 1%;
		text-align: right;
	}
	.edit-form {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.edit-form input {
		flex: 1;
		min-width: 160px;
	}
	.empty {
		padding: 20px;
		text-align: center;
	}
	@media (max-width: 640px) {
		.languages-header,
		.filters,
		.team-list {
			padding-left: 14px;
			padding-right: 14px;
		}
		.filters {
			align-items: stretch;
			flex-direction: column;
			gap: 10px;
		}
		.filters label {
			min-width: 0;
		}
	}
</style>
