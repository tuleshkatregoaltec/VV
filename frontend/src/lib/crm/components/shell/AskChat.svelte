<script lang="ts">
import MessageSquare from 'lucide-svelte/icons/message-square'
import X from 'lucide-svelte/icons/x'
import { tick } from 'svelte'
import { page } from '$app/state'
import AnswerView from '../../market/AnswerView.svelte'
import { type Answer, answer, NO_ANSWER } from '../../market/data'
import { panel } from '../../stores/panel.svelte'

/**
 * "Ask Vitevue" (call 6 Oct, 41:34-41:38): one floating chat across the CRM and Market mode.
 * UI only: Market questions get the mockup's example answers; CRM questions point to the screen
 * that answers them until the live chat is built. It only reads; it never messages a client.
 */
interface Turn {
	id: number
	q: string
	a: Answer | null
}

const SUG = {
	crm: ['Which leads have no first call?', 'What is due today?', 'Who fits Bloom Towers 707?'],
	market: [
		'What do 2 beds in JVC rent for?',
		'Which leads have no first call?',
		'What is due today?'
	]
}
const CRM_RULES: [RegExp, string, string, string][] = [
	[
		/first (call|attempt)|not called/i,
		'New leads with no call logged are on Leads, stage New.',
		'/crm/leads',
		'Open Leads'
	],
	[
		/\bdue\b|today|agenda/i,
		"Today's events and deals due are on Home and the Calendar.",
		'/crm/calendar',
		'Open Calendar'
	],
	[
		/\bfits?\b|match|who wants/i,
		'Buyers and tenants who fit a unit are on Matches, Sellers and landlords.',
		'/crm/matches',
		'Open Matches'
	]
]

let open = $state(false)
let turns = $state<Turn[]>([])
let draft = $state('')
let seq = 0
let log = $state<HTMLDivElement>()
const isMarket = $derived(page.url.pathname.startsWith('/crm/market'))
const pending = $derived(turns.some((t) => !t.a))

function reply(q: string): Answer {
	const m = answer(q)
	if (m.key) return m
	for (const [re, text, href, label] of CRM_RULES) {
		if (re.test(q))
			return {
				key: 'crm',
				text,
				ref: { href, label },
				source: 'Your CRM',
				label: 'Example · live chat in build'
			}
	}
	return { key: null, text: NO_ANSWER, source: '', label: 'Example' }
}

async function ask(q: string) {
	q = q.trim()
	if (!q || pending) return
	const id = ++seq
	turns = [...turns, { id, q, a: null }]
	draft = ''
	setTimeout(async () => {
		turns = turns.map((t) => (t.id === id ? { ...t, a: reply(q) } : t))
		await tick()
		log?.scrollTo({ top: log.scrollHeight })
	}, 450)
}

function onkeydown(e: KeyboardEvent) {
	if (e.key === 'Escape' && open) open = false
}
</script>

<svelte:window {onkeydown} />

{#if !open}
	<button
		type="button"
		class="fab"
		style:bottom={panel.current ? '76px' : undefined}
		aria-label="Ask Vitevue"
		title="Ask Vitevue"
		aria-haspopup="dialog"
		onclick={() => (open = true)}
	>
		<MessageSquare size={22} />
	</button>
{:else}
	<div class="chatp" role="dialog" aria-label="Ask Vitevue">
		<div class="chatp-h">
			<div class="kick">CRM and Market</div>
			<h2>Ask Vitevue</h2>
			<div class="sub">Example answers · the live chat is in build</div>
			<button type="button" class="ico x" aria-label="Close the chat" onclick={() => (open = false)}><X size={17} /></button>
		</div>
		<div class="chatlog" bind:this={log} aria-live="polite">
			{#each turns as t (t.id)}
				<div class="mk-q">{t.q}</div>
				<div class="mk-a">
					{#if t.a}<AnswerView a={t.a} onnav={() => (open = false)} />{:else}<span class="mk-typing" role="status" aria-label="Answering"><i></i><i></i><i></i></span>{/if}
				</div>
			{:else}
				<div class="empty"><b>No questions yet</b><span>Pick a question below or type one.</span></div>
			{/each}
		</div>
		<div class="chat-sug">
			{#each isMarket ? SUG.market : SUG.crm as q (q)}
				<button type="button" class="sugg" disabled={pending} onclick={() => ask(q)}>{q}</button>
			{/each}
			{#if turns.length}<button type="button" class="linkbtn" onclick={() => (turns = [])}>Clear</button>{/if}
		</div>
		<form class="chat-in" onsubmit={(e) => (e.preventDefault(), ask(draft))} autocomplete="off">
			<input bind:value={draft} placeholder="Ask about leads, deals or the market" aria-label="Question" />
			<button type="submit" class="btn" disabled={pending || !draft.trim()}>Ask</button>
		</form>
	</div>
{/if}
