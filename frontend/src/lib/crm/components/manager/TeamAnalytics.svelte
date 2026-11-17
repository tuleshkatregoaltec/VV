<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { AgentLeadMetrics } from '$lib/api/generated/hey-api/types.gen'
import {
	ANALYTICS_WINDOWS,
	type AnalyticsDays,
	formatMinutes,
	qualifiedRate,
	responseTone,
	TONE_LABEL,
	teamAverage
} from '../../agentMetrics'
import { crmQueries } from '../../queries'
import { ui } from '../../stores/ui.svelte'
import { errorText } from '../../write'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import Seg from '../ui/Seg.svelte'
import Skeleton from '../ui/Skeleton.svelte'

/**
 * Manager › each person's lead figures (agreed 17 Nov 2026): one card per agent and a table with
 * the team average. Every figure comes from the server; nothing is scored or ranked.
 */
const analytics = createQuery(() => crmQueries.teamAnalytics(ui.analyticsDays))

/** Lead stages in pipeline order, with the colour each takes in the stage bar. */
const STAGE_BAR: [string, string][] = [
	['new', 'var(--blue)'],
	['assigned', 'var(--blue)'],
	['needs_review', 'var(--amber)'],
	['attempted', 'var(--text3)'],
	['contacted', 'var(--text3)'],
	['qualified', 'var(--green)'],
	['viewing', 'var(--accent)'],
	['valuation', 'var(--accent)'],
	['signed', 'var(--green)'],
	['active', 'var(--green)'],
	['nurture', 'var(--text3)']
]

const initials = (name: string) =>
	name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((w) => w[0]?.toUpperCase())
		.join('') || '?'
const firstName = (name: string) => name.split(/\s+/)[0] || name
const stages = (a: AgentLeadMetrics) =>
	STAGE_BAR.map(([id, color]) => ({ id, color, n: a.by_status?.[id] ?? 0 })).filter((s) => s.n)
const pct = (n: number | null) => (n == null ? '—' : `${n}%`)
</script>

<div class="ta-head">
	<Seg
		label="Period"
		items={ANALYTICS_WINDOWS}
		value={`${ui.analyticsDays}`}
		onselect={(v) => (ui.analyticsDays = Number(v) as AnalyticsDays)}
	/>
	<span class="small muted">Recorded facts per person · open a person for their full lead analytics</span>
</div>

{#if analytics.data}
	{@const agents = analytics.data.agents}
	{#if !agents.length}
		<div class="card"><Empty text="You don’t manage a team yet." /></div>
	{:else}
		<div class="ta-cards">
			{#each agents as a (a.user_id)}
				{@const tone = responseTone(a.avg_first_response_minutes)}
				<a class="card ta-card" href="/crm/team/{a.user_id}" aria-label="{a.name}: lead analytics">
					<div class="ch">
						<span class="ta-who"><span class="ta-av" aria-hidden="true">{initials(a.name)}</span><b>{a.name}</b></span>
						<Chip tone={tone}>{TONE_LABEL[tone]}</Chip>
					</div>
					<div class="cb">
						<dl class="ta-figs">
							<div><dt>Avg first response</dt><dd>{formatMinutes(a.avg_first_response_minutes)}</dd></div>
							<div><dt>Avg lead claim time</dt><dd>{formatMinutes(a.avg_claim_minutes)}</dd></div>
							<div><dt>Contacted (last 24h)</dt><dd>{a.contacted_24h ?? 0}</dd></div>
							<div><dt>Open leads</dt><dd>{a.open_leads ?? 0}</dd></div>
						</dl>
						{#if stages(a).length}
							<div class="ta-bar" aria-hidden="true">
								{#each stages(a) as s (s.id)}<i style:flex={s.n} style:background={s.color}></i>{/each}
							</div>
							<div class="ta-legend small muted">
								{#each stages(a) as s (s.id)}<span>{s.n} {s.id.replace('_', ' ')}</span>{/each}
							</div>
						{/if}
						<span class="ta-more small">Open {firstName(a.name)}’s analytics →</span>
					</div>
				</a>
			{/each}
		</div>

		<section class="card" aria-labelledby="ta-table-h">
			<div class="ch"><h2 id="ta-table-h">Lead activity by agent</h2><span class="facts">team average in the last row</span></div>
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							<th>Agent</th><th class="r">Open leads</th><th class="r">Awaiting first contact</th>
							<th class="r">Contacted (24h)</th><th>Avg first response</th><th>Avg claim time</th>
							<th class="r">Overdue first contact</th><th class="r">Qualified or better</th>
						</tr>
					</thead>
					<tbody>
						{#each agents as a (a.user_id)}
							<tr class="row">
								<td><a class="rowlink" href="/crm/team/{a.user_id}">{a.name}</a></td>
								<td class="r num" data-label="Open leads">{a.open_leads ?? 0}</td>
								<td class="r num" data-label="Awaiting first contact">{a.awaiting_first_contact ?? 0}</td>
								<td class="r num" data-label="Contacted (24h)">{a.contacted_24h ?? 0}</td>
								<td data-label="Avg first response">{formatMinutes(a.avg_first_response_minutes)}</td>
								<td data-label="Avg claim time">{formatMinutes(a.avg_claim_minutes)}</td>
								<td class="r num" data-label="Overdue first contact">
									{#if a.overdue_first_contact}<Chip tone="red">{a.overdue_first_contact}</Chip>{:else}0{/if}
								</td>
								<td class="r num" data-label="Qualified or better">{pct(qualifiedRate(a))}</td>
							</tr>
						{/each}
						<tr class="tot">
							<td><b>Team average</b></td>
							<td class="r num">{teamAverage(agents, (a) => a.open_leads) ?? '—'}</td>
							<td class="r num">{teamAverage(agents, (a) => a.awaiting_first_contact) ?? '—'}</td>
							<td class="r num">{teamAverage(agents, (a) => a.contacted_24h) ?? '—'}</td>
							<td>{formatMinutes(teamAverage(agents, (a) => a.avg_first_response_minutes))}</td>
							<td>{formatMinutes(teamAverage(agents, (a) => a.avg_claim_minutes))}</td>
							<td class="r num">{teamAverage(agents, (a) => a.overdue_first_contact) ?? '—'}</td>
							<td class="r num">{pct(teamAverage(agents, qualifiedRate))}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</section>
	{/if}
	{#if analytics.isError}
		<ErrorLine bar message={errorText(analytics.error)} onretry={() => analytics.refetch()} />
	{/if}
{:else if analytics.isError}
	<div class="card"><ErrorLine message={errorText(analytics.error)} onretry={() => analytics.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={4} /></div>
{/if}

<style>
	.ta-head {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-bottom: 12px;
	}
	.ta-cards {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
		margin-bottom: 14px;
	}
	.ta-card {
		display: block;
		color: inherit;
		text-decoration: none;
	}
	.ta-card:hover {
		border-color: var(--accent);
	}
	.ta-who {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		flex: 1;
		min-width: 0;
	}
	.ta-av {
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
	.ta-figs {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 12px;
		margin: 0 0 12px;
	}
	.ta-figs dt {
		font-size: 12px;
		color: var(--text2);
	}
	.ta-figs dd {
		margin: 2px 0 0;
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.ta-bar {
		display: flex;
		height: 8px;
		border-radius: 5px;
		overflow: hidden;
		background: var(--sunk);
	}
	.ta-legend {
		display: flex;
		flex-wrap: wrap;
		gap: 4px 10px;
		margin-top: 5px;
	}
	.ta-more {
		display: inline-block;
		margin-top: 10px;
		color: var(--accent);
	}
	@media (max-width: 900px) {
		.ta-cards {
			grid-template-columns: 1fr;
		}
	}
</style>
