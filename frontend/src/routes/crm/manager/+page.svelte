<script lang="ts">
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/**
 * Manager view (UI only; spec: manager-view-spec.md). Example desk from the v2 mockup: six
 * tiles, the agents table, the waiting-to-assign queue and reports. The lead handout setting
 * is live on Settings. First response turns red above 10 min (v2; the spec proposes 15).
 */
type Period = 'week' | 'month' | 'quarter'
type Tab = 'agents' | 'wait' | 'reports'
const AGENTS = [
	{
		name: 'Sara A.',
		areas: 'Dubai Marina, JVC',
		fr: 4,
		open: 12,
		nfa: 0,
		vno: 0,
		deals: 4,
		detail: 'Nothing overdue. 4 deals open, 1 at mortgage.',
		comm: { week: 11000, month: 45000, quarter: 118000 }
	},
	{
		name: 'Omar K.',
		areas: 'Dubai Hills, Arabian Ranches',
		fr: 11,
		open: 15,
		nfa: 3,
		vno: 1,
		deals: 4,
		detail:
			'3 leads with no first attempt, oldest from yesterday 16:40. 1 viewing on Sat 3 Oct with no outcome.',
		comm: { week: 0, month: 28500, quarter: 96000 }
	},
	{
		name: 'Priya N.',
		areas: 'JVC, Business Bay',
		fr: 7,
		open: 13,
		nfa: 1,
		vno: 0,
		deals: 3,
		detail: '1 lead with no first attempt, from 08:50 today.',
		comm: { week: 6200, month: 19000, quarter: 64500 }
	},
	{
		name: 'Dmitri V.',
		areas: 'Palm Jumeirah, Downtown',
		fr: 18,
		open: 9,
		nfa: 4,
		vno: 2,
		deals: 3,
		detail:
			'4 leads with no first attempt, oldest from Sun 4 Oct. 2 viewings with no outcome. The assistant asked him twice.',
		comm: { week: 0, month: 0, quarter: 41000 }
	},
	{
		name: 'Layla H.',
		areas: 'Downtown, Creek Harbour',
		fr: 6,
		open: 10,
		nfa: 0,
		vno: 1,
		deals: 2,
		detail: '1 viewing from yesterday with no outcome.',
		comm: { week: 4800, month: 31000, quarter: 72000 }
	}
]
const WAITING = [
	{
		name: 'Studio enquiry',
		source: 'Dubizzle',
		text: 'Studio in the Marina, can you send photos?',
		at: '10:02',
		agent: 'Sara A.',
		reason: 'Covers Dubai Marina · first response 4 min'
	},
	{
		name: 'Villa seller',
		source: 'Email',
		text: 'I want to sell my villa in Arabian Ranches.',
		at: '08:15',
		agent: 'Omar K.',
		reason: 'Covers Arabian Ranches · speaks Arabic'
	},
	{
		name: 'Yousef Haddad',
		source: 'Bayut',
		text: 'Is the 3 bed in Maple 2 still available? Budget around 3.2m.',
		at: '08:31',
		agent: 'Omar K.',
		reason: 'Covers Dubai Hills · 4 deals there this year'
	},
	{
		name: '@jvc.renter',
		source: 'Instagram',
		text: 'How much for a 1 bed in JVC?',
		at: '10:08',
		agent: 'Priya N.',
		reason: 'Covers JVC'
	},
	{
		name: 'Lena Fischer',
		source: 'Bayut',
		text: 'Looking for a 1 bed in Dubai Marina from December, around 120k a year.',
		at: '09:58',
		agent: 'Sara A.',
		reason: 'Covers Dubai Marina · speaks English'
	}
]
const SOURCES: [string, number, number][] = [
	['Bayut', 9, 72],
	['Dubizzle', 5, 40],
	["Owners on your agency's file", 7, 56],
	['Instagram', 2, 16],
	['Email and website', 3, 24]
]
const PERIODS = [
	{ id: 'week', label: 'This week' },
	{ id: 'month', label: 'This month' },
	{ id: 'quarter', label: 'This quarter' }
] as const

let period = $state<Period>('month')
let tab = $state<Tab>('agents')
let sel = $state(3)
let assigned = $state<Record<string, true>>({})

const aed = (n: number) => `AED ${n.toLocaleString('en-US')}`
const sorted = [...AGENTS].sort((a, b) => a.fr - b.fr)
const median = sorted[Math.floor(sorted.length / 2)].fr
const slowest = [...AGENTS].sort((a, b) => b.fr - a.fr)[0]
const most = (k: 'nfa' | 'vno') => [...AGENTS].sort((a, b) => b[k] - a[k])[0]
const waiting = $derived(WAITING.filter((w) => !assigned[w.name]))
const frMax = Math.max(20, ...AGENTS.map((a) => a.fr))
const periodLabel = $derived(PERIODS.find((p) => p.id === period)?.label ?? '')
const comm = $derived(AGENTS.reduce((s, a) => s + a.comm[period], 0))

function assign(names: string[]) {
	const next = { ...assigned }
	for (const n of names) next[n] = true
	const prev = assigned
	assigned = next
	toast.show(
		`${names.length === 1 ? names[0] : `${names.length} leads`} assigned as suggested (example)`,
		{ undo: () => (assigned = prev) }
	)
}
</script>

<svelte:head><title>Manager view · CRM</title></svelte:head>

<PageHeader title="Manager view" facts="Example desk · 5 agents · {waiting.length} waiting to assign · {periodLabel}">
	{#snippet note()}<span class="mk-ex">Example</span>{/snippet}
	{#snippet right()}<a class="btn ghost" href="/crm/settings">Settings</a>{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="mk-row">
		<span class="lbl">Desk · Example</span>
		<span style:flex="1"></span>
		<Seg label="Period" items={[...PERIODS]} value={period} onselect={(v) => (period = v)} />
	</div>
	<div class="tiles6">
		<button type="button" class="kpi" onclick={() => (tab = 'wait')}><span class="lbl">Waiting to assign</span><span class="v">{waiting.length}</span><span class="n">Oldest today 08:15</span></button>
		<button type="button" class="kpi" onclick={() => (tab = 'agents')}><span class="lbl">No first attempt</span><span class="v">{AGENTS.reduce((s, a) => s + a.nfa, 0)}</span><span class="n">Most: {most('nfa').name} · {most('nfa').nfa}</span></button>
		<button type="button" class="kpi" onclick={() => (tab = 'agents')}><span class="lbl">First response · median</span><span class="v">{median} min</span><span class="n">Slowest: {slowest.name} · {slowest.fr} min</span></button>
		<button type="button" class="kpi" onclick={() => (tab = 'agents')}><span class="lbl">Commission collected</span><span class="v sm">{aed(comm)}</span><span class="n">{periodLabel.toLowerCase()} · net, all agents</span></button>
		<button type="button" class="kpi" onclick={() => (tab = 'agents')}><span class="lbl">Viewings, no outcome</span><span class="v">{AGENTS.reduce((s, a) => s + a.vno, 0)}</span><span class="n">Most: {most('vno').name} · {most('vno').vno}</span></button>
		<a class="kpi" href="/crm/calendar"><span class="lbl">Expiring in 14 days</span><span class="v">6</span><span class="n">Permits and Form A</span></a>
	</div>

	<Tabs
		label="Manager"
		items={[
			{ id: 'agents', label: 'Agents' },
			{ id: 'wait', label: 'Waiting to assign', count: waiting.length },
			{ id: 'reports', label: 'Reports' }
		]}
		value={tab}
		onselect={(t) => (tab = t)}
	/>

	{#if tab === 'agents'}
		<p class="mk-note">First response: minutes from assignment to the agent's first logged call, message or visit, median of the last 30 days. Commission collected: net commission received on the agent's deals, {periodLabel.toLowerCase()}.</p>
		<section class="card">
			<div class="tblwrap">
				<table class="tbl">
					<thead><tr><th>Agent</th><th>Areas</th><th>First response</th><th class="r">Open leads</th><th class="r">No first attempt</th><th class="r">Viewings, no outcome</th><th class="r">Deals open</th><th class="r">Commission collected</th></tr></thead>
					<tbody>
						{#each AGENTS as a, i (a.name)}
							<tr class="row" style:background={i === sel ? 'var(--sel)' : undefined}>
								<td><button type="button" class="linkbtn nm" onclick={() => (sel = i)}>{a.name}</button></td>
								<td class="sub">{a.areas}</td>
								<td>
									<span class={['barcell', a.fr > 10 && 'slow']}>
										<span class="track"><i style:width="{(100 * a.fr) / frMax}%"></i><b style:left="{(100 * 10) / frMax}%" title="10 min"></b></span>
										<span class="bv">{a.fr} min</span>
									</span>
								</td>
								<td class="r">{a.open}</td>
								<td class={['r', a.nfa > 1 && 'slow']}>{a.nfa}</td>
								<td class={['r', a.vno > 1 && 'slow']}>{a.vno}</td>
								<td class="r">{a.deals}</td>
								<td class="r">{aed(a.comm[period])}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</section>
		<section class="card">
			<div class="cb mk-row">
				<b>{AGENTS[sel].name}</b><span>{AGENTS[sel].detail}</span><span style:flex="1"></span>
				{#if AGENTS[sel].nfa > 1}
					<button type="button" class="btn ghost" onclick={() => toast.show('Reassign is in build')}>Reassign {AGENTS[sel].nfa} leads</button>
				{:else}<span class="muted">Nothing to reassign</span>{/if}
			</div>
		</section>
	{:else if tab === 'wait'}
		<section class="card">
			<div class="ch">
				<h2>Waiting to assign <span class="facts">{waiting.length}</span></h2>
				{#if waiting.length}<button type="button" class="btn sm" onclick={() => assign(waiting.map((w) => w.name))}>Assign all as suggested</button>{/if}
			</div>
			{#if waiting.length}
				<div class="tblwrap">
					<table class="tbl">
						<thead><tr><th>Enquiry</th><th>Received</th><th>Suggested agent</th><th>Reason</th><th></th></tr></thead>
						<tbody>
							{#each waiting as w (w.name)}
								<tr>
									<td><div class="nm">{w.name}</div><div class="sub">{w.source} · {w.text}</div></td>
									<td class="nowrap">Today {w.at}</td>
									<td>{w.agent}</td>
									<td class="sub">{w.reason}</td>
									<td><button type="button" class="btn sm" onclick={() => assign([w.name])}>Assign</button></td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
			{:else}
				<div class="empty">Nothing waiting. Every enquiry has an agent.</div>
			{/if}
		</section>
	{:else}
		<div class="grid-4 kpis">
			<div class="kpi"><span class="lbl">Never contacted</span><span class="v">260</span><span class="n">of 1,100 leads this quarter</span></div>
			<div class="kpi"><span class="lbl">Bought elsewhere</span><span class="v">18</span><span class="n">of those 260, matched on DLD</span></div>
			<div class="kpi"><span class="lbl">First response</span><span class="v">7 min</span><span class="n">desk median</span></div>
			<button type="button" class="kpi" onclick={() => (tab = 'agents')}><span class="lbl">Slowest agent</span><span class="v sm">{slowest.name}</span><span class="n">{slowest.fr} min · open Agents</span></button>
		</div>
		<section class="card">
			<div class="ch"><h2>Deals by lead source <span class="facts">this quarter</span></h2></div>
			<div class="cb bars">
				{#each SOURCES as [name, n, w] (name)}
					<div class="br"><span>{name}</span><span><i style:width="{w}%"></i></span><b>{n} {n === 1 ? 'deal' : 'deals'}</b></div>
				{/each}
			</div>
		</section>
	{/if}
</div>
