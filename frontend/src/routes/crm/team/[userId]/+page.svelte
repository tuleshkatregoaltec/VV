<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { ApiError } from '$lib/api/client'
import {
	ANALYTICS_WINDOWS,
	type AnalyticsDays,
	formatMinutes,
	qualifiedRate,
	responseTone,
	TONE_LABEL,
	teamAverage
} from '$lib/crm/agentMetrics'
import Chip from '$lib/crm/components/ui/Chip.svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import ErrorLine from '$lib/crm/components/ui/ErrorLine.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Skeleton from '$lib/crm/components/ui/Skeleton.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { crmQueries } from '$lib/crm/queries'
import { ui } from '$lib/crm/stores/ui.svelte'
import { errorText } from '$lib/crm/write'

/**
 * Manager › one person's lead analytics (agreed 17 Nov 2026): response and claim times against
 * the team, stages, sources, the last 7 days of activity and every lead they hold. Deal analytics
 * wait for the deals backend.
 */
const userId = $derived(page.params.userId ?? '')
const detail = createQuery(() => crmQueries.agentAnalytics(userId, ui.analyticsDays))
const team = createQuery(() => crmQueries.teamAnalytics(ui.analyticsDays))
let tab = $state<'leads' | 'deals'>('leads')

const notInTeam = $derived(detail.error instanceof ApiError && detail.error.status === 404)
const agents = $derived(team.data?.agents ?? [])

const KIND_LABEL = {
	marketing: 'Marketing (ads, portals)',
	vitevue_lease: 'Vitevue · renewal / vacancy',
	vitevue_sold: 'Vitevue · recently sold',
	own: 'Own contact / referral'
} as const
const STAGES = [
	'new',
	'assigned',
	'needs_review',
	'attempted',
	'contacted',
	'qualified',
	'viewing',
	'valuation',
	'signed',
	'active',
	'nurture'
]

const when = new Intl.DateTimeFormat('en-GB', {
	timeZone: 'Asia/Dubai',
	day: 'numeric',
	month: 'short',
	hour: '2-digit',
	minute: '2-digit'
})
const at = (iso: string | null | undefined) => (iso ? when.format(new Date(iso)) : '—')
const weekday = (iso: string) =>
	new Date(`${iso}T12:00:00Z`).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })
const status = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).replace('_', ' ')
const pct = (n: number | null) => (n == null ? '—' : `${n}%`)
</script>

<svelte:head><title>Agent analytics · CRM</title></svelte:head>

{#if detail.data}
	{@const d = detail.data}
	{@const m = d.metrics}
	{@const tone = responseTone(m.avg_first_response_minutes)}
	{@const avgResponse = teamAverage(agents, (a) => a.avg_first_response_minutes)}
	{@const avgClaim = teamAverage(agents, (a) => a.avg_claim_minutes)}
	{@const avgQualified = teamAverage(agents, qualifiedRate)}
	{@const maxStage = Math.max(1, ...STAGES.map((s) => m.by_status?.[s] ?? 0))}
	{@const maxSource = Math.max(1, ...d.sources.map((s) => s.count))}
	{@const maxDay = Math.max(1, ...d.activity.flatMap((a) => [a.calls ?? 0, a.messages ?? 0]))}
	{@const maxResponse = Math.max(1, ...agents.map((a) => a.avg_first_response_minutes ?? 0))}
	<PageHeader
		title={m.name}
		facts={`Agent analytics · ${m.team_ids?.length ?? 0} ${m.team_ids?.length === 1 ? 'team' : 'teams'} · last ${d.days} days`}
	>
		{#snippet right()}
			<button
				type="button"
				class="btn ghost"
				onclick={() => {
					ui.leadView = 'agents'
					goto('/crm/leads')
				}}
			>
				<ArrowLeft size={15} /><span>All agents</span>
			</button>
			{#if agents.length > 1}
				<select aria-label="Agent" value={userId} onchange={(e) => goto(`/crm/team/${e.currentTarget.value}`)}>
					{#each agents as a (a.user_id)}<option value={a.user_id}>{a.name}</option>{/each}
				</select>
			{/if}
		{/snippet}
	</PageHeader>

	<div class="ag-head">
		<Tabs
			label="Analytics"
			items={[
				{ id: 'leads', label: 'Leads' },
				{ id: 'deals', label: 'Deals' }
			]}
			value={tab}
			onselect={(t) => (tab = t)}
		/>
		<Seg
			label="Period"
			items={ANALYTICS_WINDOWS}
			value={`${ui.analyticsDays}`}
			onselect={(v) => (ui.analyticsDays = Number(v) as AnalyticsDays)}
		/>
		<Chip tone={tone}>{TONE_LABEL[tone]}</Chip>
	</div>

	{#if tab === 'deals'}
		<div class="card"><Empty text="Deal analytics arrive with the deals backend." /></div>
	{:else}
		<div class="grid-4 kpis">
			<div class={['kpi', m.avg_first_response_minutes != null && avgResponse != null && m.avg_first_response_minutes > avgResponse * 1.5 && 'red']}>
				<span class="lbl">Avg first response</span><span class="v">{formatMinutes(m.avg_first_response_minutes)}</span>
				<span class="n">team avg {formatMinutes(avgResponse)}</span>
			</div>
			<div class="kpi">
				<span class="lbl">Avg lead claim time</span><span class="v">{formatMinutes(m.avg_claim_minutes)}</span>
				<span class="n">from the team pool · team avg {formatMinutes(avgClaim)}</span>
			</div>
			<div class="kpi">
				<span class="lbl">Contacted (last 24h)</span><span class="v">{m.contacted_24h ?? 0}</span>
				<span class="n">leads with a logged call, message or meeting</span>
			</div>
			<div class="kpi">
				<span class="lbl">Open leads</span><span class="v">{m.open_leads ?? 0}</span>
				<span class="n">{m.awaiting_first_contact ?? 0} awaiting first contact</span>
			</div>
		</div>
		<div class="grid-4 kpis">
			<div class={['kpi', (m.overdue_first_contact ?? 0) > 0 && 'red']}>
				<span class="lbl">Overdue first contact</span><span class="v">{m.overdue_first_contact ?? 0}</span>
				<span class="n">past the first-response time</span>
			</div>
			<div class="kpi">
				<span class="lbl">Qualified or better</span><span class="v">{pct(qualifiedRate(m))}</span>
				<span class="n">of {m.assigned_in_window ?? 0} assigned · team avg {pct(avgQualified)}</span>
			</div>
			<div class="kpi">
				<span class="lbl">Assigned in period</span><span class="v">{m.assigned_in_window ?? 0}</span>
				<span class="n">last {d.days} days</span>
			</div>
			<div class="kpi">
				<span class="lbl">Last activity</span><span class="v sm">{at(m.last_activity_at)}</span>
			</div>
		</div>

		<div class="ag-grid">
			<section class="card" aria-labelledby="ag-stages">
				<div class="ch"><h2 id="ag-stages">Lead stages</h2><span class="facts">open and closed leads they hold</span></div>
				<div class="cb">
					{#each STAGES.filter((s) => m.by_status?.[s]) as s (s)}
						<div class="ag-bar"><span>{status(s)}</span><span class="track"><i style:width="{((m.by_status?.[s] ?? 0) / maxStage) * 100}%"></i></span><b>{m.by_status?.[s]}</b></div>
					{:else}
						<Empty text="No open leads." />
					{/each}
				</div>
			</section>
			<section class="card" aria-labelledby="ag-sources">
				<div class="ch"><h2 id="ag-sources">Where their leads come from</h2><span class="facts">marketing vs Vitevue leads</span></div>
				<div class="cb">
					{#each d.sources as s (s.kind + s.label)}
						<div class="ag-bar"><span>{s.label}<small class="muted">{KIND_LABEL[s.kind]}</small></span><span class="track"><i style:width="{(s.count / maxSource) * 100}%"></i></span><b>{s.count}</b></div>
					{:else}
						<Empty text="No leads yet." />
					{/each}
				</div>
			</section>
			<section class="card" aria-labelledby="ag-activity">
				<div class="ch"><h2 id="ag-activity">Activity · last 7 days</h2><span class="facts">calls and messages per day</span></div>
				<div class="cb">
					<div class="ag-cols" role="img" aria-label="Calls and messages per day, last 7 days">
						{#each d.activity as day (day.date)}
							<div class="ag-col">
								<div class="ag-pair">
									<i class="calls" style:height="{((day.calls ?? 0) / maxDay) * 100}%" title="{day.calls} calls"></i>
									<i class="msgs" style:height="{((day.messages ?? 0) / maxDay) * 100}%" title="{day.messages} messages"></i>
								</div>
								<span class="small muted">{weekday(day.date)}</span>
							</div>
						{/each}
					</div>
					<div class="ag-key small muted"><span><i class="calls"></i>Calls</span><span><i class="msgs"></i>Messages</span></div>
				</div>
			</section>
			<section class="card" aria-labelledby="ag-vs">
				<div class="ch"><h2 id="ag-vs">First response vs the team</h2><span class="facts">lower is better</span></div>
				<div class="cb">
					{#each agents as a (a.user_id)}
						<div class={['ag-bar', a.user_id === userId && 'me']}><span>{a.name}</span><span class="track"><i style:width="{((a.avg_first_response_minutes ?? 0) / maxResponse) * 100}%"></i></span><b>{formatMinutes(a.avg_first_response_minutes)}</b></div>
					{/each}
				</div>
			</section>
		</div>

		<section class="card" aria-labelledby="ag-leads">
			<div class="ch"><h2 id="ag-leads">Leads · {d.leads.length}</h2><span class="facts">overdue first, then newest</span></div>
			<div class="tblwrap">
				<table class="tbl">
					<thead><tr><th>Lead</th><th>Source</th><th>Stage</th><th>Assigned</th><th>First contact</th><th>Last contact</th><th>Next follow-up</th></tr></thead>
					<tbody>
						{#each d.leads as l (l.id)}
							<tr class="row">
								<td>
									<a class="rowlink" href="/crm/leads?lead={l.id}">{l.name}</a>
									{#if l.overdue}<Chip tone="red">Overdue</Chip>{/if}
								</td>
								<td class="sub" data-label="Source">{l.source}</td>
								<td data-label="Stage"><Chip>{status(l.status)}</Chip></td>
								<td class="sub" data-label="Assigned">{at(l.assigned_at)}</td>
								<td class="sub" data-label="First contact">{at(l.first_contact_at)}</td>
								<td class="sub" data-label="Last contact">{at(l.last_contact_at)}</td>
								<td class="sub" data-label="Next follow-up">{l.next_follow_up ?? '—'}</td>
							</tr>
						{:else}
							<tr><td colspan="7"><Empty text="No leads held." /></td></tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
	{/if}
	{#if detail.isError}
		<ErrorLine bar message={errorText(detail.error)} onretry={() => detail.refetch()} />
	{/if}
{:else if notInTeam}
	<PageHeader title="Agent analytics" />
	<div class="card"><Empty text="This person is not in a team you manage." /></div>
{:else if detail.isError}
	<PageHeader title="Agent analytics" />
	<div class="card"><ErrorLine message={errorText(detail.error)} onretry={() => detail.refetch()} /></div>
{:else}
	<PageHeader title="Agent analytics" />
	<div class="card"><Skeleton rows={6} /></div>
{/if}

<style>
	.ag-head {
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
		margin-bottom: 12px;
	}
	.ag-head :global(.tabs) {
		flex: 1;
		margin: 0;
	}
	.ag-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 14px;
		margin: 14px 0;
	}
	.ag-bar {
		display: grid;
		grid-template-columns: minmax(150px, 210px) 1fr 84px;
		gap: 10px;
		align-items: center;
		padding: 5px 0;
		font-size: 13.5px;
	}
	.ag-bar span:first-child {
		display: grid;
	}
	.ag-bar small {
		font-size: 11.5px;
	}
	.ag-bar b {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
	.ag-bar.me {
		font-weight: 600;
	}
	.track {
		height: 8px;
		background: var(--sunk);
		border-radius: 5px;
		overflow: hidden;
	}
	.track i {
		display: block;
		height: 100%;
		background: var(--accent);
	}
	.ag-bar:not(.me) .track i {
		opacity: 0.85;
	}
	.ag-cols {
		display: flex;
		gap: 8px;
		align-items: flex-end;
		height: 150px;
	}
	.ag-col {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 6px;
	}
	.ag-pair {
		display: flex;
		gap: 3px;
		align-items: flex-end;
		height: 118px;
	}
	.ag-pair i,
	.ag-key i {
		display: block;
		width: 12px;
		min-height: 2px;
		border-radius: 3px 3px 0 0;
	}
	.calls {
		background: var(--accent);
	}
	.msgs {
		background: var(--blue);
	}
	.ag-key {
		display: flex;
		gap: 14px;
		margin-top: 6px;
	}
	.ag-key span {
		display: inline-flex;
		align-items: center;
		gap: 5px;
	}
	.ag-key i {
		height: 9px;
		width: 9px;
		border-radius: 2px;
	}
	@media (max-width: 900px) {
		.ag-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
