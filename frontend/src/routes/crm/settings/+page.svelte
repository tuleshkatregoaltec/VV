<script lang="ts">
/**
 * Manager view mockup (context.md, 6 Nov): team overview for a firm's manager, on fake data.
 * Frontend only, no API calls. "View as" previews what an agent would see instead; every field
 * still under discussion carries a privacy tag for the review call.
 */

import Leaderboard from '$lib/crm/components/manager/Leaderboard.svelte'
import NeedsAttention from '$lib/crm/components/manager/NeedsAttention.svelte'
import TeamKpis from '$lib/crm/components/manager/TeamKpis.svelte'
import TeamPipeline from '$lib/crm/components/manager/TeamPipeline.svelte'
import TeamTrend from '$lib/crm/components/manager/TeamTrend.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import {
	leaderboard,
	MOCK,
	MOCK_ME_ID,
	MOCK_NOW,
	scopeFor,
	teamKpis,
	type ViewAs
} from '$lib/crm/mock/manager'
import { panel } from '$lib/crm/stores/panel.svelte'

let view = $state<ViewAs>('manager')
const data = $derived(scopeFor(view, MOCK))
const kpis = $derived(teamKpis(data))
const me = MOCK.agents.find((a) => a.id === MOCK_ME_ID)
/** My rank in the whole firm: the one number Agent view reads from unscoped data. */
const myRow = leaderboard(MOCK).find((r) => r.agent.id === MOCK_ME_ID)
const month = new Date(MOCK_NOW).toLocaleDateString('en-GB', {
	month: 'long',
	year: 'numeric',
	timeZone: 'Asia/Dubai'
})

const openAgent = (id: number) => panel.open({ kind: 'agent', id, view })

// Switching View-as with a drawer open: an agent must not keep another agent's drawer, and my
// own drawer reopens so its masking matches the new view.
$effect(() => {
	const p = panel.current
	if (p?.kind !== 'agent' || p.view === view) return
	if (view === 'agent' && p.id !== MOCK_ME_ID) panel.close()
	else panel.open({ ...p, view }, { replace: true })
})

// The agent drawer belongs to this mockup: don't leave it open on other CRM pages.
$effect(() => () => {
	if (panel.current?.kind === 'agent') panel.closeAll()
})
</script>

<svelte:head><title>Manager view · CRM Beta</title></svelte:head>

<PageHeader
	title={view === 'manager' ? 'Manager view' : 'Agent view'}
	facts={view === 'manager'
		? `Al Noor Properties · ${MOCK.agents.length} agents · mock data`
		: `Viewing as ${me?.name ?? 'an agent'} · mock data`}
>
	{#snippet right()}
		<Seg
			label="View as"
			items={[
				{ id: 'manager', label: 'Manager' },
				{ id: 'agent', label: 'Agent' }
			]}
			value={view}
			onselect={(v) => (view = v)}
		/>
	{/snippet}
</PageHeader>

<div class="banner">
	<p>Mockup with fake data, for the review call. Privacy tags mark open questions.</p>
	{#if view === 'agent'}
		<button type="button" class="btn ghost sm" onclick={() => openAgent(MOCK_ME_ID)}>Your profile</button>
	{/if}
</div>

<TeamKpis {kpis} {view} agentCount={MOCK.agents.length} {month} />
<Leaderboard {data} {view} {myRow} total={MOCK.agents.length} onopen={openAgent} />
<div class="pair">
	<TeamPipeline {data} {view} />
	<TeamTrend days={data.trend} {view} />
</div>
<NeedsAttention {data} {view} onopen={openAgent} />

<style>
	.banner {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		min-height: 32px;
		margin-bottom: 8px;
	}
	.banner p {
		margin: 0;
		color: var(--text2);
		font-size: 13px;
	}
	.pair {
		display: grid;
		gap: 16px;
	}
	@media (min-width: 1000px) {
		.pair {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
