<script lang="ts">
import { short } from '$lib/crm/format'
import { mins, type TeamKpis, type ViewAs } from '$lib/crm/mock/manager'
import PrivacyTag from './PrivacyTag.svelte'

/** Team overview tiles (Manager) or the same tiles for one agent (Agent view). */
let {
	kpis,
	view,
	agentCount,
	month
}: { kpis: TeamKpis; view: ViewAs; agentCount: number; month: string } = $props()
</script>

<section aria-labelledby="kpi-h">
	<div class="hd">
		<h2 id="kpi-h">{view === 'manager' ? 'Team overview' : 'Your numbers'}</h2>
		<PrivacyTag k="metrics" {view} />
	</div>
	<div class="tiles kpis">
		{#if view === 'manager'}
			<div class="kpi">
				<span class="lbl">Active agents</span>
				<span class="v">{kpis.activeAgents}</span>
				<span class="n">of {agentCount} · active in the last 7 days</span>
			</div>
		{/if}
		<div class="kpi">
			<span class="lbl">Open leads</span>
			<span class="v">{kpis.openLeads}</span>
			<span class="n">not won or lost</span>
		</div>
		<div class="kpi">
			<span class="lbl">Pipeline value</span>
			<span class="v">AED {short(kpis.pipelineAed)}</span>
			<span class="n">open leads only</span>
		</div>
		<div class={['kpi', kpis.wonThisMonth > 0 && 'green']}>
			<span class="lbl">Deals won this month</span>
			<span class="v">{kpis.wonThisMonth}</span>
			<span class="n">{month}</span>
		</div>
		<div class="kpi">
			<span class="lbl">Median first reply</span>
			<span class="v">{mins(kpis.medianReplyMins)}</span>
			<span class="n">{view === 'manager' ? 'middle agent, last 30 days' : 'your median, last 30 days'}</span>
		</div>
		<div class={['kpi', kpis.overdueFollowUps > 0 && 'red']}>
			<span class="lbl">Overdue follow-ups</span>
			<span class="v">{kpis.overdueFollowUps}</span>
			<span class="n">past their due date</span>
		</div>
	</div>
</section>

<style>
	section {
		margin-bottom: 16px;
	}
	.hd {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 8px;
	}
	h2 {
		margin: 0;
		font-size: 15.5px;
		font-weight: 600;
		letter-spacing: -0.01em;
	}
	.tiles {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
		gap: 12px;
	}
</style>
