<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowLeft from 'lucide-svelte/icons/arrow-left'
import Ban from 'lucide-svelte/icons/ban'
import CheckCheck from 'lucide-svelte/icons/check-check'
import CircleAlert from 'lucide-svelte/icons/circle-alert'
import Clock3 from 'lucide-svelte/icons/clock-3'
import Hand from 'lucide-svelte/icons/hand'
import Sparkles from 'lucide-svelte/icons/sparkles'
import { ApiError } from '$lib/api/client'
import type { CustomerMessageResponse } from '$lib/api/generated/hey-api/types.gen'
import { whatsapp } from '$lib/api/whatsapp'
import { whatsappConnect } from '$lib/api/whatsapp-connect'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappKeys, whatsappQueries } from '$lib/queries/whatsapp'
import { whatsappConnectKeys } from '$lib/queries/whatsapp-connect'
import {
	avatarText,
	buildTranscript,
	clock,
	formatPhone,
	THREAD_STATE_LABEL,
	threadState
} from '$lib/whatsapp/chat'

// The agent's view of what customers actually saw: each conversation drawn as a chat, with
// held replies editable in place. Replies typed in the WhatsApp app itself are not stored.
let { connectionId }: { connectionId: string } = $props()
const queryClient = getQueryClient()

const notifications = createQuery(() => whatsappQueries.notifications())
const threads = createQuery(() => whatsappQueries.threads(connectionId))
let chosen = $state<string | null>(null)
let mobileChat = $state(false)
let busy = $state(false)
let editing = $state<string | null>(null)
let draftText = $state('')

const pending = $derived(
	new Set(
		(notifications.data ?? [])
			.filter((m) => m.status === 'approval_required')
			.map((m) => m.thread_id)
	)
)
const ordered = $derived(
	[...(threads.data ?? [])].sort((a, b) => {
		const pa = pending.has(a.id) ? 1 : 0
		const pb = pending.has(b.id) ? 1 : 0
		return pb - pa || b.updated_at.localeCompare(a.updated_at)
	})
)
const thread = $derived(ordered.find((t) => t.id === chosen) ?? ordered[0] ?? null)
const messages = createQuery(() => whatsappQueries.messages(thread?.id ?? null))
const items = $derived(buildTranscript(messages.data ?? []))
const tstate = $derived(thread ? threadState(thread, pending) : null)

let scroller = $state<HTMLDivElement | null>(null)
let lastCount = 0
$effect(() => {
	// Follow new bubbles the way a chat app does, without fighting a reader who scrolled up.
	const count = items.length
	const el = scroller
	if (!el || count === lastCount) return
	const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
	if (lastCount === 0 || nearBottom) queueMicrotask(() => el.scrollTo({ top: el.scrollHeight }))
	lastCount = count
})
$effect(() => {
	void thread?.id
	lastCount = 0
	editing = null
})

function open(id: string) {
	chosen = id
	mobileChat = true
}

async function run(action: () => Promise<unknown>, done: string) {
	if (busy) return
	busy = true
	try {
		await action()
		toast.show(done)
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.status === 409
				? 'This reply changed while you were looking. The chat has been refreshed; check it and try again.'
				: e instanceof ApiError && e.message
					? e.message
					: 'Could not save that change. Try again.',
			{ tone: 'error' }
		)
	} finally {
		await queryClient.invalidateQueries({ queryKey: whatsappKeys.all })
		busy = false
	}
}

// One tap for the personal contact who slipped through: the assistant ignores them from now
// on, and the number can be unblocked again from the Block list tab.
async function block(sender: string) {
	await run(
		async () => {
			await whatsappConnect.setBlocked({ phone_numbers: [sender], blocked: true })
			await queryClient.invalidateQueries({ queryKey: whatsappConnectKeys.all })
		},
		`Blocked ${formatPhone(sender)}. Their messages are no longer read. Undo in the Block list tab.`
	)
}

function startEdit(m: CustomerMessageResponse) {
	editing = m.id
	draftText = m.reply ?? ''
}

async function saveEdit(m: CustomerMessageResponse) {
	await run(
		() => whatsapp.edit(m.id, { expected_revision: m.revision, reply: draftText }),
		'Draft saved. Send it when you are ready.'
	)
	editing = null
}

const tagClass: Record<string, string> = {
	review: 'amber',
	yours: 'ink',
	auto: 'teal',
	optout: 'red'
}
</script>

<div class={['mirror', mobileChat && 'show-chat']}>
	<aside class="threads" aria-label="Conversations">
		<div class="th">
			<h2>Conversations</h2>
			<span class="count">{threads.data?.length ?? 0}</span>
		</div>
		{#if threads.isPending}
			<p class="quiet">Loading conversations…</p>
		{:else if threads.isError}
			<p class="quiet">Could not load conversations. <button type="button" class="linkbtn" onclick={() => threads.refetch()}>Retry</button></p>
		{:else if ordered.length === 0}
			<p class="quiet">No customer has messaged this number since automation was switched on. New enquiries appear here as they arrive.</p>
		{:else}
			<ul>
				{#each ordered as t (t.id)}
					{@const s = threadState(t, pending)}
					<li>
						<button type="button" class="tr" aria-current={thread?.id === t.id ? 'true' : undefined} onclick={() => open(t.id)}>
							<span class="av" aria-hidden="true">{avatarText(t.sender)}</span>
							<span class="tw">
								<span class="tn">{formatPhone(t.sender)}</span>
								<span class={['tag', tagClass[s]]}>{THREAD_STATE_LABEL[s]}</span>
							</span>
							<time class="tt" datetime={t.updated_at}>{clock(t.updated_at)}</time>
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</aside>

	<section class="chat" aria-label="Conversation">
		{#if thread && tstate}
			<header class="ch">
				<button type="button" class="back" aria-label="Back to conversations" onclick={() => (mobileChat = false)}><ArrowLeft size={18} /></button>
				<span class="av lg" aria-hidden="true">{avatarText(thread.sender)}</span>
				<div class="who">
					<b>{formatPhone(thread.sender)}</b>
					<span>{THREAD_STATE_LABEL[tstate]}</span>
				</div>
				{#if !thread.opted_out}
					{#if thread.paused}
						<button type="button" class="btn ghost sm" disabled={busy} onclick={() => run(() => whatsapp.resume(thread.id), 'The assistant will answer this customer’s next message.')}>Let the assistant reply</button>
					{:else}
						<button type="button" class="btn ghost sm" disabled={busy} onclick={() => run(() => whatsapp.takeover(thread.id), 'You’re handling this chat. The assistant will stay quiet here.')}>I’ll handle this</button>
					{/if}
				{/if}
				<button type="button" class="btn plain sm block" disabled={busy} onclick={() => block(thread.sender)} aria-label={`Block ${formatPhone(thread.sender)}`}><Ban size={14} aria-hidden="true" /><span>Block</span></button>
			</header>

			<div class="wall" bind:this={scroller} aria-live="polite">
				{#if messages.isPending}
					<p class="sys">Loading messages…</p>
				{:else if messages.isError}
					<p class="sys">Could not load this chat. <button type="button" class="linkbtn" onclick={() => messages.refetch()}>Retry</button></p>
				{/if}
				{#each items as item (item.key)}
					{#if item.kind === 'day'}
						<div class="day"><span>{item.label}</span></div>
					{:else if item.kind === 'in'}
						<div class="b in">
							<p class={[!item.text && 'gone']}>{item.text ?? 'Message text not kept. Read it in WhatsApp.'}</p>
							<time datetime={item.at}>{clock(item.at)}</time>
						</div>
					{:else if item.kind === 'out'}
						<div class={['b out', item.state === 'failed' && 'bad']}>
							<span class="by"><Sparkles size={11} aria-hidden="true" /> Assistant</span>
							<p>{item.text}</p>
							<span class="meta">
								<time datetime={item.at}>{clock(item.at)}</time>
								{#if item.state === 'sent'}<CheckCheck size={14} aria-label="Sent" />
								{:else if item.state === 'queued'}<Clock3 size={13} aria-label="Waiting to send" />
								{:else}<CircleAlert size={13} aria-label="Not sent" />{/if}
							</span>
							{#if item.note}<span class="why">{item.note}</span>{/if}
						</div>
					{:else if item.kind === 'handoff'}
						<div class="handoff">
							<span class="hk"><Hand size={13} aria-hidden="true" /> Handed to you</span>
							<p>{item.text}</p>
						</div>
					{:else if item.kind === 'draft'}
						{@const m = item.message}
						<div class="b out draft" data-message={m.id}>
							<span class="by">Held for your approval</span>
							{#if editing === m.id}
								<label class="sr" for={`edit-${m.id}`}>Reply to send</label>
								<textarea id={`edit-${m.id}`} bind:value={draftText} rows="4" maxlength={4000}></textarea>
								<div class="acts">
									<button type="button" class="btn sm" disabled={busy || !draftText.trim() || draftText === (m.reply ?? '')} onclick={() => saveEdit(m)}>Save draft</button>
									<button type="button" class="btn plain sm" disabled={busy} onclick={() => (editing = null)}>Cancel edit</button>
								</div>
							{:else}
								<p class={[!m.reply && 'gone']}>{m.reply ?? 'No draft was written. Reply from WhatsApp, or discard.'}</p>
								<div class="acts">
									<button type="button" class="btn sm" disabled={busy || !m.reply?.trim()} onclick={() => run(() => whatsapp.approve(m.id, m.revision), 'Reply sent to WhatsApp.')}>Send reply</button>
									<button type="button" class="btn ghost sm" disabled={busy} onclick={() => startEdit(m)}>Edit</button>
									<button type="button" class="btn plain sm" disabled={busy} onclick={() => run(() => whatsapp.cancel(m.id, m.revision), 'Draft discarded. Nothing was sent.')}>Discard</button>
								</div>
							{/if}
						</div>
					{:else if item.kind === 'discarded'}
						<div class="b out ghosted">
							<span class="by">Not sent · {item.note}</span>
							<p>{item.text}</p>
						</div>
					{:else if item.kind === 'quiet'}
						<p class="sys">{item.text}</p>
					{:else if item.kind === 'typing'}
						<div class="b in typing" aria-label="Assistant is preparing a reply"><i></i><i></i><i></i></div>
					{/if}
				{/each}
			</div>

			<footer class="cf">
				{#if thread.opted_out}
					This customer sent STOP. They must send START before anything is sent again.
				{:else}
					To write to this customer yourself, use the WhatsApp app on your phone. The assistant stays quiet in this chat after you reply there. Your own replies are not shown here.
				{/if}
			</footer>
		{:else}
			<div class="empty">
				<p><b>Pick a conversation</b> to see exactly what the customer saw.</p>
			</div>
		{/if}
	</section>
</div>

<style>
.mirror {
	--wall: #f3efe6;
	--wall-line: rgba(28, 52, 74, 0.035);
	--wall-major: rgba(28, 52, 74, 0.07);
	--bub-in: var(--card);
	--bub-out: #e2eef2;
	--bub-out-ink: #12384a;
	display: grid;
	grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
	height: min(720px, calc(100dvh - 230px));
	min-height: 480px;
	border: 1px solid var(--sep);
	border-radius: 10px;
	overflow: hidden;
	background: var(--card);
}
:global(:root[data-theme='dark']) .mirror {
	--wall: #0d1824;
	--wall-line: rgba(203, 213, 225, 0.04);
	--wall-major: rgba(203, 213, 225, 0.07);
	--bub-out: #173a4b;
	--bub-out-ink: #e3f0f5;
}

/* Conversation list */
.threads { display: flex; flex-direction: column; min-height: 0; border-right: 1px solid var(--sep); }
.th { display: flex; align-items: baseline; gap: 8px; padding: 14px 16px 10px; border-bottom: 1px solid var(--sep); }
.th h2 { margin: 0; font-size: 14px; font-weight: 600; }
.count { font-size: 12px; color: var(--text3); font-variant-numeric: tabular-nums; }
.threads ul { list-style: none; margin: 0; padding: 0; overflow: auto; }
.tr { display: grid; grid-template-columns: 36px minmax(0, 1fr) auto; gap: 10px; align-items: center; width: 100%; padding: 10px 16px; text-align: left; border-bottom: 1px solid var(--sep); }
.tr:hover { background: var(--hover); }
.tr[aria-current='true'] { background: var(--sel); box-shadow: inset 3px 0 0 var(--accent); }
.tr:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.tw { display: grid; gap: 3px; min-width: 0; }
.tn { font-size: 13.5px; font-weight: 550; font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tt { align-self: start; font-size: 11.5px; color: var(--text3); font-variant-numeric: tabular-nums; }
.tag { justify-self: start; font-size: 11.5px; font-weight: 500; color: var(--text3); }
.tag.amber { color: var(--amber); }
.tag.teal { color: var(--accent); }
.tag.red { color: var(--red); }
.av { display: grid; place-items: center; width: 36px; height: 36px; border-radius: 50%; background: var(--sunk); color: var(--text2); font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; letter-spacing: .02em; }
.av.lg { width: 38px; height: 38px; }

/* Chat */
.chat { display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.ch { display: flex; align-items: center; gap: 10px; padding: 10px 16px; border-bottom: 1px solid var(--sep); background: var(--card); }
.back { display: none; }
.block { display: inline-flex; align-items: center; gap: 5px; color: var(--text2); }
.block:hover:not(:disabled) { color: var(--red); }
.who { display: grid; flex: 1; min-width: 0; line-height: 1.3; }
.who b { font-family: var(--font-display); font-size: 16px; font-weight: 560; letter-spacing: -.005em; font-variant-numeric: lining-nums tabular-nums; }
.who span { font-size: 12px; color: var(--text3); }

.wall {
	flex: 1;
	min-height: 0;
	overflow: auto;
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding: 18px clamp(12px, 4%, 40px) 22px;
	background-color: var(--wall);
	/* A drafting-paper grid: the room where property deals are drawn up. */
	background-image:
		linear-gradient(var(--wall-major) 1px, transparent 1px),
		linear-gradient(90deg, var(--wall-major) 1px, transparent 1px),
		linear-gradient(var(--wall-line) 1px, transparent 1px),
		linear-gradient(90deg, var(--wall-line) 1px, transparent 1px);
	background-size: 120px 120px, 120px 120px, 24px 24px, 24px 24px;
}
.day { align-self: center; margin: 8px 0 6px; }
.day span { display: inline-block; padding: 3px 10px; border-radius: 6px; background: var(--card); color: var(--text3); font-size: 11.5px; font-weight: 500; box-shadow: var(--shadow); }

.b { position: relative; max-width: min(78%, 520px); padding: 7px 10px 6px; border-radius: 10px; font-size: 14px; line-height: 1.45; box-shadow: 0 1px 1px rgba(15, 23, 42, .06); }
.b p { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.b time, .meta { font-size: 11px; color: var(--text3); font-variant-numeric: tabular-nums; }
.b.in { align-self: flex-start; background: var(--bub-in); border-top-left-radius: 3px; }
.b.in time { display: block; text-align: right; margin-top: 2px; }
.b.out { align-self: flex-end; background: var(--bub-out); color: var(--bub-out-ink); border-top-right-radius: 3px; }
.b.out .meta { display: flex; justify-content: flex-end; align-items: center; gap: 4px; margin-top: 2px; color: inherit; opacity: .7; }
.by { display: inline-flex; align-items: center; gap: 4px; margin-bottom: 2px; font-size: 11px; font-weight: 600; letter-spacing: .02em; color: var(--accent); }
:global(:root[data-theme='dark']) .b.out .by { color: #8cc6da; }
.b.bad { box-shadow: inset 0 0 0 1px var(--red); }
.why { display: block; margin-top: 4px; font-size: 12px; color: var(--red); }
.gone { font-style: italic; color: var(--text3); }

.b.draft { background: var(--amber-bg); color: var(--text); border: 1.5px dashed var(--amber); box-shadow: none; }
.b.draft .by { color: var(--amber); }
.b.draft textarea { width: min(460px, 100%); margin-top: 4px; padding: 8px; border: 1px solid var(--sep-strong); border-radius: 6px; background: var(--card); color: var(--text); font: inherit; resize: vertical; }
.acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.b.ghosted { background: transparent; border: 1px dashed var(--sep-strong); box-shadow: none; color: var(--text3); }
.b.ghosted p { text-decoration: line-through; text-decoration-color: color-mix(in srgb, currentColor 45%, transparent); }
.b.ghosted .by { color: var(--text3); font-weight: 500; }

.handoff { align-self: center; max-width: min(88%, 560px); margin: 8px 0; padding: 9px 14px; border-radius: 10px; background: var(--card); border: 1px solid var(--sep); box-shadow: var(--shadow); font-size: 13px; line-height: 1.5; color: var(--text2); }
.handoff p { margin: 2px 0 0; }
.hk { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .06em; color: var(--amber); }
.sys { align-self: center; margin: 4px 0; font-size: 12px; color: var(--text3); background: var(--card); padding: 3px 10px; border-radius: 6px; }

.typing { display: inline-flex; gap: 4px; padding: 11px 12px; }
.typing i { width: 6px; height: 6px; border-radius: 50%; background: var(--text3); animation: blink 1.2s infinite ease-in-out; }
.typing i:nth-child(2) { animation-delay: .15s; }
.typing i:nth-child(3) { animation-delay: .3s; }
@keyframes blink { 0%, 80%, 100% { opacity: .25; } 40% { opacity: 1; } }
@media (prefers-reduced-motion: reduce) { .typing i { animation: none; opacity: .6; } }

.cf { padding: 10px 16px; border-top: 1px solid var(--sep); background: var(--sunk); font-size: 12.5px; line-height: 1.5; color: var(--text3); }
.empty { flex: 1; display: grid; place-items: center; padding: 24px; background-color: var(--wall); color: var(--text2); font-size: 13.5px; text-align: center; }
.empty p { margin: 0; max-width: 34ch; }
.quiet { margin: 0; padding: 20px 16px; font-size: 13px; line-height: 1.5; color: var(--text3); }
.linkbtn { color: var(--accent); font-weight: 500; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

@media (max-width: 760px) {
	.mirror { grid-template-columns: 1fr; height: calc(100dvh - 210px); }
	.chat { display: none; }
	.show-chat .threads { display: none; }
	.show-chat .chat { display: flex; }
	.back { display: grid; place-items: center; width: 32px; height: 32px; margin-left: -6px; border-radius: 6px; }
	.b { max-width: 88%; }
	.ch { gap: 8px; padding: 8px 10px; }
	.ch .av { display: none; }
	.who b { font-size: 15px; white-space: nowrap; }
	.block span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }
}
</style>
