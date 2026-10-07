<script lang="ts">
import Mic from 'lucide-svelte/icons/mic'
import Undo2 from 'lucide-svelte/icons/undo-2'
import { goto } from '$app/navigation'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/**
 * Assistant (UI only, example day from the v2 mockup): the agent's Telegram chat on the left,
 * what it wrote into the CRM on the right. Each change is written only after the agent
 * confirms, and each one can be undone. Nothing here reaches the backend yet.
 */
type Origin = 'rule' | 'model' | 'voice' | 'human'
interface Msg {
	s: string
	time: string
	who: 'bot' | 'me' | 'voice' | 'photos'
	text: string
	tag?: string
	dur?: string
	names?: string[]
	rows?: string[]
	kb?: string[]
	confirm?: { ref: string; origin: Origin; rows: [string, string, string][] }
}
interface Write {
	id: number
	msg: number
	time: string
	ref: string
	origin: Origin
	rows: [string, string, string][]
	undone: boolean
}

const TG: Msg[] = [
	{
		s: 'Morning brief',
		time: '08:00',
		who: 'bot',
		text: 'Good morning. Yesterday in your areas: 2 sales and 5 new leases in Dubai Marina, 1 sale in JVC.'
	},
	{
		s: 'Morning brief',
		time: '08:00',
		who: 'bot',
		text: 'Today: 2 calls, 2 viewings, 1 follow-up. Viewing with Faisal Al Marri at 11:00. First call with Ahmed Al Hashimi at 12:00. Viewing with Sofia Rossi at 14:00.',
		kb: ['Calendar', 'Leads']
	},
	{
		s: 'New enquiry',
		time: '09:40',
		who: 'bot',
		tag: 'High priority',
		text: "New enquiry · Bayut · 3 bed, Dubai Hills. Khalid Al Suwaidi, +971 50 ••• 118. His phone matches an owner on your agency's file: 2 units in JVC, both let."
	},
	{
		s: 'New enquiry',
		time: '09:51',
		who: 'me',
		text: 'Called him. Wants to see 2 options this week, budget 4.5 million, cash.'
	},
	{
		s: 'New enquiry',
		time: '09:51',
		who: 'bot',
		text: "Khalid Al Suwaidi. I'll set:\n· Stage → Contacted\n· Budget → AED 4,500,000\n· Finance → Cash\n· Next → 2 viewings this week",
		confirm: {
			ref: 'Khalid Al Suwaidi',
			origin: 'model',
			rows: [
				['Stage', 'New', 'Contacted'],
				['Budget', '—', 'AED 4,500,000'],
				['Finance', '—', 'Cash'],
				['Next action', 'First call', '2 viewings this week']
			]
		}
	},
	{
		s: 'After a viewing',
		time: '11:20',
		who: 'voice',
		dur: '0:22',
		text: 'Just finished with Faisal. Liked the Dubai Hills three-bed, wants a second viewing Saturday at 11, budget up to 3 million, pre-approved with Emirates NBD.'
	},
	{
		s: 'After a viewing',
		time: '11:20',
		who: 'bot',
		text: "Faisal Al Marri. I'll set:\n· Stage → Viewing done\n· Budget → AED 3,000,000\n· Finance → Pre-approved, Emirates NBD\n· Second viewing → Sat 11:00",
		confirm: {
			ref: 'Faisal Al Marri',
			origin: 'voice',
			rows: [
				['Stage', 'Viewing booked', 'Viewing done'],
				['Budget', 'AED 2,800,000', 'AED 3,000,000'],
				['Finance', 'Mortgage', 'Pre-approved, Emirates NBD'],
				['Calendar', '', 'Sat 10 Oct 11:00 · second viewing']
			]
		}
	},
	{
		s: 'Client request',
		time: '13:05',
		who: 'me',
		text: 'Aisha Rahman wants a 1 bed in JVC, up to 1.1m, cash, moving by 1 Dec.'
	},
	{
		s: 'Client request',
		time: '13:05',
		who: 'bot',
		text: 'Aisha Rahman · 1 bed · JVC · up to AED 1,100,000',
		rows: [
			'3 company listings',
			"1 owner on your agency's file with a prior deal and a lease ending before 1 Dec",
			'1 more on your file with no prior deal record: add one before contacting',
			'4 portal listings, agent to agent'
		],
		kb: ['Open matches']
	},
	{
		s: 'Ownership change',
		time: '14:40',
		who: 'bot',
		tag: 'Ownership change',
		text: 'Hamdan S. sold unit 3402, Burj Vista 1. The sale shows in DLD on 3 Oct. You last spoke to him on 12 Sep about a pocket listing.',
		kb: ['Open the lead']
	},
	{
		s: 'Missed update',
		time: '16:30',
		who: 'bot',
		text: "What happened at Sofia Rossi's viewing at 14:00?"
	},
	{
		s: 'Missed update',
		time: '16:31',
		who: 'voice',
		dur: '0:15',
		text: 'She liked it but needs to move on the 1st of November, and that unit is only free on the 15th.'
	},
	{
		s: 'Missed update',
		time: '16:31',
		who: 'bot',
		text: "Sofia Rossi. I'll set:\n· Outcome → Liked it, date does not fit\n· Next → Units free by 1 Nov",
		confirm: {
			ref: 'Sofia Rossi',
			origin: 'voice',
			rows: [
				['Viewing outcome', '—', 'Liked it, date does not fit'],
				['Next action', 'Viewing, Oxford Residence', 'Units free by 1 Nov']
			]
		}
	},
	{
		s: 'Deal documents',
		time: '17:30',
		who: 'photos',
		names: ['Title deed', "Manager's cheque"],
		text: "Title deed and the manager's cheque for DL-201"
	},
	{
		s: 'Deal documents',
		time: '17:30',
		who: 'bot',
		text: "DL-201 · Marina Gate 2. I'll file:\n· Title deed\n· Manager's cheque\nStill missing after this: NOC.",
		confirm: {
			ref: 'DL-201',
			origin: 'model',
			rows: [
				['Title deed', 'Missing', 'On file'],
				["Manager's cheque", 'Missing', 'On file']
			]
		}
	},
	{
		s: 'End of day',
		time: '18:00',
		who: 'bot',
		text: 'Today: 14 calls logged, 2 viewings updated, 1 new lead, 2 documents filed.'
	}
]
const KB_LINKS: Record<string, string> = {
	Calendar: '/crm/calendar',
	Leads: '/crm/leads',
	'Open matches': '/crm/matches',
	'Open the lead': '/crm/leads'
}
const ORIGIN: Record<Origin, string> = {
	voice: 'Voice note',
	model: 'Assistant',
	rule: 'Rule',
	human: 'Typed'
}
const scenes = [...new Set(TG.map((m) => m.s))]

let log = $state<Write[]>([
	{
		id: 1,
		msg: 2,
		time: '09:40',
		ref: 'Khalid Al Suwaidi',
		origin: 'rule',
		rows: [
			['Lead created', '', 'Bayut enquiry'],
			['Owner match', '', "On your agency's file · 2 units in JVC"]
		],
		undone: false
	}
])
let chat = $state<HTMLDivElement>()
let seq = 1

const active = $derived(log.filter((w) => !w.undone).length)
const saved = (i: number) => log.some((w) => w.msg === i && !w.undone)

function confirm(i: number) {
	const m = TG[i]
	if (!m.confirm) return
	const ex = log.find((w) => w.msg === i)
	if (ex) {
		ex.undone = false
	} else {
		log.push({
			id: ++seq,
			msg: i,
			time: m.time,
			ref: m.confirm.ref,
			origin: m.confirm.origin,
			rows: m.confirm.rows,
			undone: false
		})
	}
	toast.show(`Saved from Telegram · ${m.confirm.ref} (example)`, { undo: () => setUndone(i, true) })
}
function setUndone(msg: number, v: boolean) {
	const w = log.find((x) => x.msg === msg)
	if (w) w.undone = v
}
function jump(i: number) {
	const el = document.getElementById(`scene-${i}`)
	if (el && chat) chat.scrollTop = el.offsetTop - chat.offsetTop - 8
}
</script>

<svelte:head><title>Assistant · CRM</title></svelte:head>

<PageHeader title="Assistant" facts="Telegram · example day Tue 6 Oct · changes are written after the agent confirms">
	{#snippet note()}<span class="mk-ex">Example</span>{/snippet}
</PageHeader>

<div class="asst">
	<div class="phone" aria-label="Telegram chat, example">
		<div class="ph-h">
			<span class="avatar">V</span>
			<div><b>Vitevue assistant</b><div class="muted small">Your chat · bot</div></div>
		</div>
		<div class="scenes">
			{#each scenes as sc, i (sc)}<button type="button" class="btn plain sm" onclick={() => jump(i)}>{sc}</button>{/each}
		</div>
		<div class="tgchat" bind:this={chat}>
			{#each TG as m, i (i)}
				{#if i === 0 || TG[i - 1].s !== m.s}
					<div class="scene" id="scene-{scenes.indexOf(m.s)}">{m.s} · {m.time}</div>
				{/if}
				<div class={['bub', m.who !== 'bot' && 'me']}>
					{#if m.tag}<span class="tag">{m.tag}</span><br />{/if}
					{#if m.who === 'voice'}
						<span class="mk-row"><Mic size={15} aria-hidden="true" /> Voice note · {m.dur}</span>
						<div class="small" style:opacity="0.8" style:margin-top="4px">{m.text}</div>
					{:else if m.who === 'photos'}
						<div class="mk-row">{#each m.names ?? [] as n (n)}<span class="chip">{n}.jpg</span>{/each}</div>
						<div style:margin-top="4px">{m.text}</div>
					{:else}
						{m.text}
					{/if}
					{#if m.rows}<ul>{#each m.rows as r (r)}<li>{r}</li>{/each}</ul>{/if}
					{#if m.confirm}
						<div class="kb">
							<button type="button" disabled={saved(i)} onclick={() => confirm(i)}>{saved(i) ? 'Saved ✓' : 'Confirm ✓'}</button>
							<button type="button" onclick={() => toast.show('Change opens the record to edit (in build)')}>Change</button>
						</div>
					{:else if m.kb}
						<div class="kb">{#each m.kb as k (k)}<button type="button" onclick={() => goto(KB_LINKS[k])}>{k}</button>{/each}</div>
					{/if}
					<span class="tm">{m.time}</span>
				</div>
			{/each}
		</div>
	</div>

	<section class="card" aria-labelledby="as-log" style:display="flex" style:flex-direction="column" style:min-height="0">
		<div class="ch"><h2 id="as-log">Written to the CRM <span class="facts">{active} {active === 1 ? 'change' : 'changes'} today · each one can be undone</span></h2></div>
		<div class="wlog" style:overflow="auto" style:flex="1">
			{#each [...log].reverse() as w (w.id)}
				<div class={['wr', w.undone && 'undone']}>
					<span class="mono small muted">{w.time}</span>
					<div>
						<div class="mk-row"><b>{w.ref}</b><span class={['oc', w.origin]}>{ORIGIN[w.origin]}</span></div>
						<div class="chg">
							{#each w.rows as [k, from, to] (k)}<div><span class="muted">{k}:</span> {from ? `${from} → ` : ''}<b>{to}</b></div>{/each}
						</div>
					</div>
					{#if w.undone}
						<button type="button" class="btn ghost sm" onclick={() => setUndone(w.msg, false)}>Redo</button>
					{:else}
						<button type="button" class="btn ghost sm" onclick={() => setUndone(w.msg, true)}><Undo2 size={14} aria-hidden="true" />Undo</button>
					{/if}
				</div>
			{:else}
				<Empty text="Nothing written yet. Confirm a change in the chat to write it into the CRM." />
			{/each}
		</div>
	</section>
</div>
