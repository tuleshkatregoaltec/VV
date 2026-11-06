<script lang="ts">
import { SvelteSet } from 'svelte/reactivity'
import { short } from '$lib/crm/format'
import {
	ago,
	leaderboard,
	MOCK,
	maskEmail,
	maskPhone,
	mins,
	scopeFor,
	type ViewAs
} from '$lib/crm/mock/manager'
import PrivacyTag from '../manager/PrivacyTag.svelte'
import Empty from '../ui/Empty.svelte'
import Kv from '../ui/Kv.svelte'
import Panel from '../ui/Panel.svelte'
import StageChip from '../ui/StageChip.svelte'

/**
 * Manager view mockup: one agent's numbers, leads and activity. Reads through `scopeFor`, so in
 * Agent view another agent's drawer has nothing to show. Manager sees contacts masked with a
 * per-lead Reveal, and activity counts, never message content (privacy matrix defaults).
 */
let { id, view }: { id: number; view: ViewAs } = $props()

const d = $derived(scopeFor(view, MOCK))
const agent = $derived(d.agents.find((a) => a.id === id))
const row = $derived(leaderboard(MOCK).find((r) => r.agent.id === id))
const leads = $derived(
	d.leads
		.filter((l) => l.agentId === id)
		.sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
)
const activity = $derived(d.activity.filter((x) => x.agentId === id))

let tab = $state('overview')
const revealed = new SvelteSet<number>()

const KIND = { reply: 'Reply', viewing: 'Viewing', stage: 'Stage', note: 'Note' } as const
const pct = (c: number | null | undefined) => (c == null ? '—' : `${c}%`)
</script>

{#if agent}
	<Panel
		kicker="Agent"
		title={agent.name}
		sub="Last active {ago(agent.lastActiveAt)}"
		tabs={[
			{ id: 'overview', label: 'Overview' },
			{ id: 'leads', label: 'Leads', count: leads.length },
			{ id: 'activity', label: 'Activity', count: activity.length }
		]}
		{tab}
		ontab={(t) => (tab = t)}
	>
		{#if tab === 'overview'}
			<div class="kv">
				<Kv k="Rank" v={row ? `#${row.rank} of ${MOCK.agents.length}` : '—'} o="by deals won" />
				<Kv k="Deals won" v={row?.won ?? 0} />
				<Kv k="Leads" v={row?.leads ?? 0} />
				<Kv k="Conversion" v={pct(row?.conversion)} />
				<Kv k="Replies" v={agent.replies30d} o="last 30 days" />
				<Kv k="Avg response" v={mins(agent.medianReplyMins)} />
				<Kv k="Matches sent" v={agent.matches30d} o="last 30 days" />
				<Kv k="Overdue follow-ups" v={agent.overdueFollowUps} />
			</div>
		{:else if tab === 'leads'}
			<div class="note">
				{#if view === 'manager'}
					Contacts are hidden until you reveal one.
					<PrivacyTag k="phoneEmail" {view} name="phone/email" />
					<PrivacyTag k="contacts" {view} name="contacts" />
				{:else}
					Your leads, with full contacts.
					<PrivacyTag k="contacts" {view} />
				{/if}
			</div>
			<div class="list">
				{#each leads as l (l.id)}
					{@const show = view === 'agent' || revealed.has(l.id)}
					<div class="li">
						<StageChip stage={l.stage} />
						<div class="min-w-0">
							<div class="t">{l.name}</div>
							<div class="d">AED {short(l.valueAed)} · {l.source} · {ago(l.createdAt)}</div>
							<div class="d contact">
								{show ? l.phone : maskPhone(l.phone)} · {show ? l.email : maskEmail(l.email)}
							</div>
						</div>
						{#if view === 'manager' && !revealed.has(l.id)}
							<button type="button" class="btn ghost sm" onclick={() => revealed.add(l.id)}>Reveal</button>
						{:else}
							<span></span>
						{/if}
					</div>
				{:else}
					<Empty text="No leads assigned yet." />
				{/each}
			</div>
		{:else}
			{#if view === 'manager'}
				<div class="note">
					What happened, not what was said: message content isn't shown.
					<PrivacyTag k="messages" {view} />
				</div>
			{/if}
			<div class="list">
				{#each activity as x, i (i)}
					<div class="li">
						<span class="kind">{KIND[x.kind]}</span>
						<div class="t">{x.text}</div>
						<span class="d">{ago(x.at)}</span>
					</div>
				{:else}
					<Empty text="No activity in the last 7 days." />
				{/each}
			</div>
		{/if}
	</Panel>
{:else}
	<!-- Agent view: someone else's drawer. Never show their data, say why instead. -->
	<Panel kicker="Agent" title="Not available">
		<Empty text="Agents can only see their own profile." />
	</Panel>
{/if}

<style>
	.note {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 6px;
		margin-bottom: 10px;
		font-size: 13px;
		color: var(--text2);
	}
	.list {
		margin: 0 -1rem;
	}
	.contact {
		font-variant-numeric: tabular-nums;
	}
	.kind {
		font-size: 11.5px;
		font-weight: 600;
		color: var(--text2);
		min-width: 56px;
	}
</style>
