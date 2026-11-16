<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Mail from 'lucide-svelte/icons/mail'
import Search from 'lucide-svelte/icons/search'
import TriangleAlert from 'lucide-svelte/icons/triangle-alert'
import UserRound from 'lucide-svelte/icons/user-round'
import UsersRound from 'lucide-svelte/icons/users-round'
import type { TeamWorkload } from '$lib/api/generated/hey-api/types.gen'
import { fmt, fullDate } from '../../format'
import { crmQueries } from '../../queries'
import QueryView from '../ui/QueryView.svelte'

const workload = createQuery(() => crmQueries.workload())
let teamId = $state('')
let search = $state('')
const searchTerm = $derived(search.trim().toLocaleLowerCase())

function matchesSearch(value: string | null | undefined) {
	return !searchTerm || (value ?? '').toLocaleLowerCase().includes(searchTerm)
}

function total(
	team: TeamWorkload,
	key: 'open_leads' | 'awaiting_first_contact' | 'overdue_first_contact'
) {
	return team.members.reduce((sum, member) => sum + (member[key] ?? 0), 0)
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

<section class="card workload" aria-labelledby="workload-h">
	<header class="workload-header">
		<span class="header-icon" aria-hidden="true"><UsersRound size={25} /></span>
		<div>
			<h2 id="workload-h">Team workload</h2>
			<p class="small muted">Open leads only. Overdue: past the lead’s first-response time with no contact logged.</p>
		</div>
	</header>

	<QueryView query={workload} rows={3}>
		{#snippet children(data)}
			<div class="filters">
				<label>
					<span>Team</span>
					<select bind:value={teamId}>
						<option value="">All teams</option>
						{#each data.teams as team (team.team_id)}
							<option value={team.team_id}>{team.name}</option>
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
				{#each data.teams.filter((team) => (teamId === '' || team.team_id === teamId) && team.members.some((member) => matchesSearch(member.name))) as team (team.team_id)}
					<section class="team">
						<header class="team-header">
							<div class="team-name">
								<UsersRound size={21} aria-hidden="true" />
								<h3>{team.name}</h3>
								<span class="pool">{fmt(team.unassigned ?? 0)} unassigned{team.shared ? ' · ' + fmt(team.shared) + ' shared' : ''}</span>
							</div>
							<div class="metrics" aria-label={team.name + ' summary'}>
								<div class="metric">
									<Mail size={18} aria-hidden="true" />
									<span><strong>{fmt(total(team, 'open_leads'))}</strong>Open leads</span>
								</div>
								<div class="metric">
									<UserRound size={18} aria-hidden="true" />
									<span><strong>{fmt(total(team, 'awaiting_first_contact'))}</strong>Awaiting first contact</span>
								</div>
								<div class="metric overdue">
									<TriangleAlert size={18} aria-hidden="true" />
									<span><strong>{fmt(total(team, 'overdue_first_contact'))}</strong>Overdue</span>
								</div>
							</div>
						</header>

						<div class="tblwrap">
							<table class="tbl">
								<caption class="sr-only">{team.name}: open leads per person</caption>
								<thead>
									<tr>
										<th scope="col">Person</th>
										<th scope="col">Open leads</th>
										<th scope="col">Awaiting first contact</th>
										<th scope="col">Overdue</th>
										<th scope="col">Last activity</th>
									</tr>
								</thead>
								<tbody>
									{#each team.members.filter((member) => matchesSearch(member.name)) as member (member.user_id)}
										<tr>
											<th scope="row" class="person">
												<span class="avatar">{initials(member.name || 'Former member')}</span>
												{member.name || 'Former member'}
											</th>
											<td data-label="Open leads">
												{fmt(member.open_leads ?? 0)}
												{#if member.open_leads}<span class="new-count">{Object.values(member.by_status ?? {}).reduce((sum, count) => sum + count, 0)} new</span>{/if}
											</td>
											<td data-label="Awaiting first contact">{fmt(member.awaiting_first_contact ?? 0)}</td>
											<td data-label="Overdue" class:late={Boolean(member.overdue_first_contact)}>
												{fmt(member.overdue_first_contact ?? 0)}
											</td>
											<td data-label="Last activity" class="sub">
												{member.last_activity_at ? fullDate(member.last_activity_at.slice(0, 10)) : '—'}
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
	.workload {
		display: grid;
		gap: 0;
		padding: 0;
		overflow: hidden;
	}
	.workload-header {
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
	.workload h2,
	.team h3 {
		margin: 0;
	}
	.workload h2 {
		font-size: 21px;
	}
	.workload p {
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
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
		padding: 11px 16px;
		background: var(--sunk);
	}
	.team-name {
		display: flex;
		align-items: center;
		gap: 9px;
		min-width: 180px;
	}
	.team-name h3 {
		font-size: 17px;
	}
	.pool,
	.new-count {
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
	.metrics {
		display: grid;
		grid-template-columns: repeat(3, minmax(145px, 1fr));
		gap: 9px;
	}
	.metric {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 7px 10px;
		border-radius: 8px;
		background: var(--card);
		color: var(--accent);
	}
	.metric span {
		display: grid;
		color: var(--text2);
		font-size: 11px;
		line-height: 1.2;
	}
	.metric strong {
		color: var(--text);
		font-size: 16px;
	}
	.metric.overdue {
		color: var(--red);
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
	.late {
		color: var(--red);
		font-weight: 700;
	}
	.empty {
		padding: 20px;
		text-align: center;
	}
	@media (max-width: 900px) {
		.team-header {
			align-items: start;
			flex-direction: column;
		}
		.metrics {
			width: 100%;
		}
	}
	@media (max-width: 640px) {
		.workload-header,
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
		.metrics {
			grid-template-columns: 1fr;
		}
	}
</style>
