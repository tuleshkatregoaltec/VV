<script lang="ts">
import {
	type AgentRow,
	ago,
	leaderboard,
	type MgrData,
	mins,
	type SortKey,
	sortRows,
	type ViewAs
} from '$lib/crm/mock/manager'
import PrivacyTag from './PrivacyTag.svelte'

/**
 * Manager: every agent, sortable, a row opens the agent drawer. Agent: only their own rank
 * (privacy matrix default "own rank only", marked for the call).
 */
let {
	data,
	view,
	myRow,
	total,
	onopen
}: {
	data: MgrData
	view: ViewAs
	/** My row from the whole firm's leaderboard (the one number Agent view reads unscoped). */
	myRow: AgentRow | undefined
	total: number
	onopen?: (agentId: number) => void
} = $props()

const COLS: { key: SortKey; label: string; right?: boolean }[] = [
	{ key: 'name', label: 'Agent' },
	{ key: 'leads', label: 'Leads', right: true },
	{ key: 'replies', label: 'Replies (30d)', right: true },
	{ key: 'response', label: 'Avg response', right: true },
	{ key: 'matches', label: 'Matches', right: true },
	{ key: 'deals', label: 'Deals won', right: true },
	{ key: 'conversion', label: 'Conversion', right: true },
	{ key: 'lastActive', label: 'Last active' }
]

let sort = $state<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'deals', dir: 'desc' })
const rows = $derived(sortRows(leaderboard(data), sort.key, sort.dir))

function sortBy(key: SortKey) {
	// Names read A→Z first; numbers biggest first.
	sort =
		sort.key === key
			? { key, dir: sort.dir === 'asc' ? 'desc' : 'asc' }
			: { key, dir: key === 'name' ? 'asc' : 'desc' }
}

const pct = (c: number | null) => (c === null ? '—' : `${c}%`)
</script>

<section class="card" aria-labelledby="lb-h">
	<div class="ch">
		<h2 id="lb-h">
			{view === 'manager' ? 'Agent leaderboard' : 'Your ranking'}
		</h2>
		<PrivacyTag k={view === 'manager' ? 'metrics' : 'ranking'} {view} />
	</div>

	{#if view === 'manager'}
		<div class="tblwrap">
			<table class="tbl">
				<thead>
					<tr>
						{#each COLS as c (c.key)}
							<th
								class={[c.right && 'r']}
								aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
							>
								<button type="button" class="sortbtn" onclick={() => sortBy(c.key)}>
									{c.label}<span class="arrow" aria-hidden="true"
										>{sort.key === c.key ? (sort.dir === 'asc' ? '↑' : '↓') : ''}</span
									>
								</button>
							</th>
						{/each}
					</tr>
				</thead>
				<tbody>
					{#each rows as r (r.agent.id)}
						<tr class="row">
							<td>
								<span class="who">
									<span class="rk" aria-label="Rank {r.rank}">{r.rank}</span>
									<span class="av" aria-hidden="true">{r.agent.initials}</span>
									<button type="button" class="rowlink" onclick={() => onopen?.(r.agent.id)}>
										{r.agent.name}
									</button>
								</span>
							</td>
							<td class="r" data-label="Leads">{r.leads}</td>
							<td class="r" data-label="Replies (30d)">{r.agent.replies30d}</td>
							<td class="r" data-label="Avg response">{mins(r.agent.medianReplyMins)}</td>
							<td class="r" data-label="Matches">{r.agent.matches30d}</td>
							<td class="r nm" data-label="Deals won">{r.won}</td>
							<td class="r" data-label="Conversion">{pct(r.conversion)}</td>
							<td class="sub" data-label="Last active">{ago(r.agent.lastActiveAt)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else if myRow}
		<p class="mine">
			You're <b>#{myRow.rank}</b> of {total} by deals won
			<span class="sub">· {myRow.won} won · {pct(myRow.conversion)} conversion</span>
		</p>
	{/if}
</section>

<style>
	section {
		margin-bottom: 16px;
	}
	.sortbtn {
		font: inherit;
		color: inherit;
		background: none;
		border: 0;
		padding: 0;
		cursor: pointer;
		white-space: nowrap;
	}
	.sortbtn:hover {
		color: var(--text);
	}
	.arrow {
		margin-left: 2px;
	}
	/* No space held for the arrow when unsorted, so right-aligned headers line up with their numbers. */
	.arrow:empty {
		display: none;
	}
	.who {
		display: inline-flex;
		align-items: center;
		gap: 8px;
	}
	.rk {
		min-width: 2ch;
		text-align: right;
		color: var(--text2);
		font-size: 13px;
		font-variant-numeric: tabular-nums;
	}
	.av {
		display: grid;
		place-items: center;
		width: 26px;
		height: 26px;
		border-radius: 50%;
		background: var(--sunk);
		color: var(--text2);
		font-size: 11px;
		font-weight: 600;
		flex: none;
	}
	.mine {
		margin: 0;
		padding: 14px;
		font-size: 15px;
	}
	.mine .sub {
		color: var(--text2);
		font-size: 13px;
	}
</style>
