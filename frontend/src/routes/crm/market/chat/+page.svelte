<script lang="ts">
import { tick } from 'svelte'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import AnswerView from '$lib/crm/market/AnswerView.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { CHAT_FOOTER, QUESTIONS, screen } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import { market } from '$lib/crm/market/state.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** AI chat (UI only): example answers with the source and the period; the thread is shared with Ask Vitevue. */
const s = screen('chat')
let draft = $state('')
let log = $state<HTMLDivElement>()

async function ask(q: string) {
	q = q.trim()
	if (!q) return
	market.ask(q)
	draft = ''
	await tick()
	log?.scrollTo({ top: log.scrollHeight })
}
function clear() {
	const prev = market.chat
	market.chat = []
	toast.show(`History cleared · ${prev.length} answers`, { undo: () => (market.chat = prev) })
}
function focus(id: number) {
	document.getElementById(`mk-turn-${id}`)?.scrollIntoView({ block: 'nearest' })
}
</script>

<svelte:head><title>AI chat · Market</title></svelte:head>

<PageHeader title={s.label} facts="Answers from DLD sales and Ejari leases, with the source and the period · {market.chat.length} in history · Example answers">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}<button type="button" class="btn ghost" disabled={!market.chat.length} onclick={clear}>Clear history</button>{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="mk-gchat">
		<div class="mk-col">
			<section class="card" aria-labelledby="mk-qs">
				<div class="ch"><h2 id="mk-qs">Questions</h2><Lab src="ex" /></div>
				<div class="mk-qs">
					{#each QUESTIONS as q (q.key)}<button type="button" class="mk-qbtn" onclick={() => ask(q.q)}>{q.q}</button>{/each}
				</div>
			</section>
			<section class="card" aria-labelledby="mk-hist">
				<div class="ch"><h2 id="mk-hist">History <span class="facts">{market.chat.length}</span></h2></div>
				<div class="list">
					{#each [...market.chat].reverse().slice(0, 20) as t (t.id)}
						<button type="button" class="li" onclick={() => focus(t.id)}><span></span><span><div class="t">{t.q}</div><div class="d">{t.at}</div></span><span></span></button>
					{:else}
						<Empty text="Nothing asked yet." />
					{/each}
				</div>
			</section>
		</div>

		<section class="card" aria-labelledby="mk-thread">
			<div class="ch"><h2 id="mk-thread">Thread <span class="facts">{market.chat.length} answers</span></h2></div>
			<div class="mk-chatlog" bind:this={log} aria-live="polite">
				{#each market.chat as t (t.id)}
					<div class="mk-stack" id="mk-turn-{t.id}">
						<div class="mk-q">{t.q}</div>
						<div class="mk-a">
							{#if t.a}
								<AnswerView a={t.a} />
								<div><button type="button" class="btn plain sm" onclick={() => market.removeTurn(t.id)}>Remove</button></div>
							{:else}
								<span class="mk-typing" role="status" aria-label="Answering"><i></i><i></i><i></i></span>
							{/if}
						</div>
					</div>
				{:else}
					<Empty text="No questions yet. Pick a question on the left or type one." />
				{/each}
			</div>
			<form class="mk-askform" onsubmit={(e) => (e.preventDefault(), ask(draft))} autocomplete="off">
				<input bind:value={draft} placeholder="Ask about prices, rents, yields or launches" aria-label="Ask a question" />
				<button type="submit" class="btn" disabled={!draft.trim()}>Ask</button>
			</form>
			<p class="mk-note mk-pad">{CHAT_FOOTER} <span class="mk-tag mk-neu">In build</span></p>
		</section>
	</div>
</div>
