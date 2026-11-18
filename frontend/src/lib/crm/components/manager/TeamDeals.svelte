<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { AgentDealSummary } from '$lib/api/generated/hey-api/types.gen'
import { fmt, short } from '../../format'
import { crmQueries } from '../../queries'
import { errorText } from '../../write'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import Skeleton from '../ui/Skeleton.svelte'

/**
 * Manager › each agent's deals (Kian, 18 Nov 2026): how many deals each person under you has,
 * which steps they are at, their value, and where they came from. Every figure is counted from
 * stored deals, so an agent opening or moving a deal shows here on the next refresh.
 */
const oversight = createQuery(() => crmQueries.dealOversight())
const scope = createQuery(() => crmQueries.assignmentScope())
const me = createQuery(() => crmQueries.me())

const names = $derived(new Map((scope.data?.people ?? []).map((p) => [p.user_id, p.name])))
/** In an agent's own view the only person is themselves; elsewhere an unlisted id is a colleague. */
const nameOf = (id: string | null | undefined) =>
	!id
		? 'Unassigned'
		: (names.get(id) ??
			(oversight.data?.scope === 'own' ? (me.data?.name ?? 'You') : 'Another agent'))

/** Steps in conveyancing order (sale, then rent), each with a colour for the stage bar. */
const STEP_COLORS: Record<string, string> = {
	'Offer accepted': 'var(--blue)',
	'Form F signed': 'var(--blue)',
	'Mortgage / bank': 'var(--amber)',
	NOC: 'var(--amber)',
	'Transfer booked': 'var(--accent)',
	Transferred: 'var(--green)',
	Contract: 'var(--blue)',
	'Deposit and cheques': 'var(--amber)',
	Ejari: 'var(--accent)',
	Keys: 'var(--green)'
}
const ORDER = Object.keys(STEP_COLORS)
const steps = (a: AgentDealSummary) =>
	Object.entries(a.by_stage ?? {})
		.sort(([x], [y]) => ORDER.indexOf(x) - ORDER.indexOf(y))
		.map(([name, n]) => ({ name, n, color: STEP_COLORS[name] ?? 'var(--text3)' }))
const origins = (a: AgentDealSummary, labels: Record<string, string>) =>
	Object.entries(a.by_origin ?? {})
		.sort(([, x], [, y]) => y - x)
		.map(([id, n]) => ({ id, n, label: labels[id] ?? id }))
const when = (at: string | null | undefined) =>
	at ? new Date(at).toLocaleDateString(undefined, { day: 'numeric', month: 'short' }) : '—'
const initials = (name: string) =>
	name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0]?.toUpperCase())
		.join('') || '?'
</script>

{#if oversight.data}
	{@const o = oversight.data}
	{@const labels = o.origin_labels}
	<div class="td-head">
		<span class="small muted">
			{o.scope === 'organization' ? 'Everyone in the organisation' : o.scope === 'teams' ? 'The agents in your teams' : 'Your deals'}
			· open deals, steps, value and where they came from
		</span>
	</div>
	{#if !o.agents.length}
		<div class="card"><Empty text="No agents to show yet." /></div>
	{:else}
		<div class="td-cards">
			{#each o.agents as a (a.user_id ?? 'none')}
				{@const name = nameOf(a.user_id)}
				<article class="card td-card" aria-label="{name}: deals">
					<div class="ch">
						<span class="td-who"><span class="td-av" aria-hidden="true">{initials(name)}</span><b>{name}</b></span>
						{#if a.won_30d}<Chip tone="green">{a.won_30d} won · 30 days</Chip>{/if}
					</div>
					<div class="cb">
						<dl class="td-figs">
							<div><dt>Open deals</dt><dd>{a.open}</dd></div>
							<div><dt>Open value</dt><dd>{a.open_value_aed ? `AED ${short(a.open_value_aed)}` : '—'}</dd></div>
							<div><dt>Average value</dt><dd>{a.average_value_aed ? `AED ${short(a.average_value_aed)}` : '—'}</dd></div>
							<div><dt>Last deal activity</dt><dd class="sm">{when(a.last_activity_at)}</dd></div>
						</dl>
						{#if steps(a).length}
							<div class="td-bar" aria-hidden="true">
								{#each steps(a) as s (s.name)}<i style:flex={s.n} style:background={s.color}></i>{/each}
							</div>
							<div class="td-legend small muted">
								{#each steps(a) as s (s.name)}<span>{s.n} {s.name}</span>{/each}
							</div>
						{/if}
						{#if origins(a, labels).length}
							<div class="td-origins" aria-label="Where {name}'s open deals came from">
								{#each origins(a, labels) as x (x.id)}<Chip>{x.n} {x.label}</Chip>{/each}
							</div>
						{:else if !a.open}
							<p class="small muted td-none">No open deals.</p>
						{/if}
					</div>
				</article>
			{/each}
		</div>

		<section class="card" aria-labelledby="td-table-h">
			<div class="ch"><h2 id="td-table-h">Deals by agent</h2><span class="facts">totals in the last row</span></div>
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Agent</th><th class="r">Open</th><th class="r">Open value</th><th class="r">Average</th>
							<th class="r">Won (30 days)</th><th class="r">Lost (30 days)</th><th>Came from</th>
						</tr>
					</thead>
					<tbody>
						{#each o.agents as a (a.user_id ?? 'none')}
							<tr class="row">
								<td>{nameOf(a.user_id)}</td>
								<td class="r num" data-label="Open">{a.open}</td>
								<td class="r num" data-label="Open value">{a.open_value_aed ? fmt(a.open_value_aed) : '—'}</td>
								<td class="r num" data-label="Average">{a.average_value_aed ? fmt(a.average_value_aed) : '—'}</td>
								<td class="r num" data-label="Won (30 days)">{a.won_30d}</td>
								<td class="r num" data-label="Lost (30 days)">{a.lost_30d}</td>
								<td class="sub" data-label="Came from">
									{origins(a, labels).map((x) => `${x.n} ${x.label}`).join(' · ') || '—'}
								</td>
							</tr>
						{/each}
						<tr class="tot">
							<td><b>Total</b></td>
							<td class="r num"><b>{o.totals.open}</b></td>
							<td class="r num"><b>{o.totals.open_value_aed ? fmt(o.totals.open_value_aed) : '—'}</b></td>
							<td class="r num">{o.totals.average_value_aed ? fmt(o.totals.average_value_aed) : '—'}</td>
							<td class="r num">{o.totals.won_30d}</td>
							<td class="r num">{o.totals.lost_30d}</td>
							<td class="sub">{origins(o.totals, labels).map((x) => `${x.n} ${x.label}`).join(' · ') || '—'}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</section>
	{/if}
	{#if oversight.isError}
		<ErrorLine bar message={errorText(oversight.error)} onretry={() => oversight.refetch()} />
	{/if}
{:else if oversight.isError}
	<div class="card"><ErrorLine message={errorText(oversight.error)} onretry={() => oversight.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={4} /></div>
{/if}

<style>
	.td-head {
		margin-bottom: 12px;
	}
	.td-cards {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 14px;
	}
	.td-who {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		min-width: 0;
	}
	.td-av {
		display: inline-grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: 50%;
		background: var(--sel);
		color: var(--accent);
		font-size: 11px;
		font-weight: 700;
		flex: none;
	}
	.td-figs {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		margin: 0 0 12px;
	}
	.td-figs dt {
		font-size: 12px;
		color: var(--text2);
	}
	.td-figs dd {
		margin: 2px 0 0;
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.td-figs dd.sm {
		font-size: 15px;
	}
	.td-bar {
		display: flex;
		height: 8px;
		border-radius: 5px;
		overflow: hidden;
		background: var(--sunk);
	}
	.td-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		margin-top: 5px;
	}
	.td-origins {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-top: 10px;
	}
	.td-none {
		margin: 0;
	}
	@media (max-width: 900px) {
		.td-cards {
			grid-template-columns: 1fr;
		}
	}
</style>
