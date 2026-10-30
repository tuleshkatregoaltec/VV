<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import DOMPurify from 'dompurify'
import Send from 'lucide-svelte/icons/send'
import { Marked } from 'marked'
import { browser } from '$app/environment'
import { type AssistantMessageResponse, assistant, assistantKeys } from '../api'
import { applyEvent, type ProposedAction, parseEvent, type ThreadMessage } from '../stream'
import ActionCard from './ActionCard.svelte'

/** The chat thread: stored turns, the reply streaming in, and cards for proposed changes. */
let {
	conversationId,
	ensureConversation
}: {
	conversationId: number | null
	/** Creates a conversation when the agent sends the first message of a new chat. */
	ensureConversation: () => Promise<number>
} = $props()

const SUGGESTIONS = [
	'Leads with follow-ups due today',
	'Summarise my new leads this week',
	'Move Ahmed to qualified',
	"Share Sara's lead with Omar",
	'What’s on my calendar this week?'
]

// Own instance, so market chat's link settings are untouched. Lead links stay in the CRM tab.
const markdown = new Marked({
	renderer: {
		link({ href: raw, title, text }) {
			// The model sometimes adds a domain to a CRM link; keep CRM links inside the app.
			const href = raw.replace(/^https?:\/\/[^/]+(?=\/crm\/)/, '')
			const titleAttr = title ? ` title="${title}"` : ''
			const external = !href.startsWith('/')
			const target = external ? ' target="_blank" rel="noopener noreferrer"' : ''
			return `<a href="${href}"${titleAttr}${target}>${text}</a>`
		}
	}
})
const SANITIZE = {
	ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'a', 'ul', 'ol', 'li', 'blockquote', 'code'],
	ALLOWED_ATTR: ['href', 'title', 'target', 'rel']
}
function render(content: string): string {
	if (!browser) return content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
	return DOMPurify.sanitize(markdown.parse(content) as string, SANITIZE)
}

const queryClient = useQueryClient()
const messagesQuery = createQuery(() => ({
	queryKey: assistantKeys.messages(conversationId ?? 0),
	queryFn: () => assistant.getMessages(conversationId as number),
	enabled: conversationId !== null
}))

let thread = $state<ThreadMessage[]>([])
let input = $state('')
let streaming = $state(false)
// A failed turn stores no reply, so its error is kept here; re-syncing the stored turns would
// otherwise wipe it from the thread.
let turnError = $state<string | null>(null)
let stream: { close: () => void } | null = null
let streamFor: number | null = null
let endRef: HTMLDivElement | undefined = $state()

const toThread = (rows: AssistantMessageResponse[]): ThreadMessage[] =>
	rows.map((row) => ({
		role: row.role === 'user' ? 'user' : 'assistant',
		content: row.content,
		actions: ((row.meta_data?.actions as ProposedAction[] | undefined) ?? []).filter(Boolean)
	}))

// Stored turns win whenever no reply is streaming in.
$effect(() => {
	const rows = messagesQuery.data
	if (streaming) return
	thread = conversationId === null ? [] : toThread(rows ?? [])
})

// Leaving a conversation stops its stream.
$effect(() => {
	if (stream && streamFor !== conversationId) {
		stream.close()
		stream = null
		streaming = false
	}
})

$effect(() => {
	void thread.length
	void thread.at(-1)?.content.length
	endRef?.scrollIntoView({ behavior: 'smooth', block: 'end' })
})

async function finish(id: number) {
	stream = null
	void queryClient.invalidateQueries({ queryKey: assistantKeys.conversations() })
	// Keep showing the streamed reply until the stored turns are back; switching earlier would
	// briefly show the cached history without it.
	await queryClient.invalidateQueries({ queryKey: assistantKeys.messages(id) }).catch(() => {})
	streaming = false
}

async function send(text = input) {
	const message = text.trim()
	if (!message || streaming) return
	input = ''
	turnError = null
	streaming = true
	thread = [
		...thread,
		{ role: 'user', content: message, actions: [] },
		{ role: 'assistant', content: '', actions: [], status: 'Thinking…' }
	]
	let id: number
	try {
		id = conversationId ?? (await ensureConversation())
	} catch {
		turnError = 'Could not start a conversation. Try again.'
		streaming = false
		return
	}
	streamFor = id
	stream = await assistant.sendMessage(id, message, (chunk) => {
		const event = parseEvent(chunk)
		if (!event || streamFor !== id) return
		if (event.type === 'error') {
			turnError =
				event.error === 'token_limit_exceeded'
					? 'You have used today’s assistant limit. Try again tomorrow.'
					: 'The assistant could not answer. Try again in a moment.'
		}
		thread = applyEvent(thread, event)
		if (event.type === 'done' || event.type === 'error') void finish(id)
	})
}

function onKeydown(e: KeyboardEvent) {
	if (e.key === 'Enter' && !e.shiftKey) {
		e.preventDefault()
		void send()
	}
}
</script>

<section class="thread">
	<div class="scroll">
		{#if messagesQuery.isError}
			<p class="err" role="alert">Could not load this conversation.</p>
		{/if}

		{#if thread.length === 0 && !messagesQuery.isLoading}
			<div class="intro">
				<h2>Ask about your leads</h2>
				<p>
					I can find leads, check your calendar, and prepare changes and bookings for you to
					confirm. I only see your organisation’s leads.
				</p>
				<div class="suggestions">
					{#each SUGGESTIONS as suggestion (suggestion)}
						<button type="button" class="btn ghost sm" onclick={() => send(suggestion)}>
							{suggestion}
						</button>
					{/each}
				</div>
			</div>
		{/if}

		{#each thread as message, i (i)}
			<div class={['msg', message.role]}>
				{#if message.role === 'user'}
					<div class="bubble">{message.content}</div>
				{:else}
					{#if message.content}
						<div class="md">{@html render(message.content)}</div>
					{/if}
					{#each message.actions as action, j (action.action_id ?? `copy-${j}`)}
						<ActionCard {action} />
					{/each}
					{#if message.status}<p class="status">{message.status}</p>{/if}
					{#if message.error}<p class="err" role="alert">{message.error}</p>{/if}
				{/if}
			</div>
		{/each}
		{#if turnError && !streaming}
			<p class="err" role="alert">{turnError}</p>
		{/if}
		<div bind:this={endRef}></div>
	</div>

	<form
		class="composer"
		onsubmit={(e) => {
			e.preventDefault()
			void send()
		}}
	>
		<textarea
			aria-label="Message the assistant"
			placeholder="Ask about your leads…"
			rows="1"
			bind:value={input}
			onkeydown={onKeydown}
		></textarea>
		<button type="submit" class="btn" disabled={streaming || !input.trim()} aria-label="Send">
			<Send size={15} />
		</button>
	</form>
</section>

<style>
	.thread {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.scroll {
		flex: 1;
		overflow-y: auto;
		padding: 16px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}
	.intro {
		margin: auto;
		max-width: 520px;
		text-align: center;
	}
	.intro h2 {
		font-size: 17px;
		margin: 0 0 6px;
	}
	.intro p {
		color: var(--text2);
		margin: 0 0 12px;
	}
	.suggestions {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		justify-content: center;
	}
	.suggestions .btn {
		white-space: normal;
		height: auto;
		min-height: 28px;
		padding: 4px 10px;
	}
	.msg.user {
		align-self: flex-end;
		max-width: 80%;
	}
	.msg.assistant {
		max-width: 92%;
	}
	.bubble {
		background: var(--sel);
		border-radius: 12px;
		padding: 8px 12px;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
	}
	.md :global(p) {
		margin: 0 0 8px;
	}
	.md :global(ul),
	.md :global(ol) {
		margin: 0 0 8px;
		padding-left: 20px;
	}
	.md :global(a) {
		color: var(--accent);
	}
	.md :global(blockquote) {
		margin: 0 0 8px;
		padding-left: 10px;
		border-left: 3px solid var(--sep-strong);
		color: var(--text2);
	}
	.status {
		color: var(--text2);
		font-size: 13px;
		margin: 4px 0 0;
	}
	.err {
		color: var(--red);
		font-size: 13px;
		margin: 4px 0 0;
	}
	.composer {
		display: flex;
		gap: 8px;
		padding: 10px 12px;
		border-top: 1px solid var(--sep);
		align-items: flex-end;
	}
	textarea {
		flex: 1;
		resize: none;
		min-height: 36px;
		max-height: 160px;
		field-sizing: content;
	}
</style>
