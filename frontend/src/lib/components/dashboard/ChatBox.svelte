<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import DOMPurify from 'dompurify'
import Mic from 'lucide-svelte/icons/mic'
import { marked } from 'marked'
import { cubicOut } from 'svelte/easing'
import { fade, fly } from 'svelte/transition'
import { browser } from '$app/environment'
import { type ChatAssistant, chat, type MessageResponse } from '$lib/api/chat'
import { artifactSortValue, type ChatArtifact, isChatArtifact } from '$lib/chat/artifacts'
import { describeChatError } from '$lib/chat/errors'
import { safeChatHref } from '$lib/chat/safeLinks'
import { applyTurnEvent, type TurnView } from '$lib/chat/toolLabels'
import VoicePanel from '$lib/chat/voice/VoicePanel.svelte'
import { voiceSupported } from '$lib/chat/voice/voice.svelte'
import ChatActionCard from '$lib/components/chat/ChatActionCard.svelte'
import ChatArtifactBubble from '$lib/components/chat/ChatArtifactBubble.svelte'
import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte'
import { chatKeys, chatQueries } from '$lib/queries/chat'

const SANITIZE_CONFIG = {
	ALLOWED_TAGS: [
		'p',
		'br',
		'strong',
		'em',
		'a',
		'ul',
		'ol',
		'li',
		'blockquote',
		'code',
		'pre',
		'span',
		// Answers listing several records use Markdown tables (one row per record).
		'table',
		'thead',
		'tbody',
		'tr',
		'th',
		'td'
	],
	ALLOWED_ATTR: ['href', 'title', 'target', 'rel']
}

function renderMarkdown(content: string): string {
	if (!browser) return content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
	const fragment = DOMPurify.sanitize(marked.parse(content) as string, {
		...SANITIZE_CONFIG,
		RETURN_DOM_FRAGMENT: true
	})
	for (const link of fragment.querySelectorAll('a')) {
		const href = safeChatHref(link.getAttribute('href') ?? '', window.location.origin)
		if (href) link.setAttribute('href', href)
		else link.removeAttribute('href')
		link.setAttribute('rel', 'noopener noreferrer')
	}
	const container = document.createElement('div')
	container.append(fragment)
	return container.innerHTML
}

let {
	conversationId = $bindable(null),
	initialMessage = null,
	autoSend = false,
	showHeader = true,
	voice = false,
	assistant = 'crm',
	onMessageSent = () => {}
}: {
	conversationId: number | null
	initialMessage?: string | null
	autoSend?: boolean
	showHeader?: boolean
	/** Show the microphone: speak a message, check the words, then send. */
	voice?: boolean
	/** Which product answers: the CRM Operations Assistant (default) or Market AI (/chat). */
	assistant?: ChatAssistant
	onMessageSent?: () => void
} = $props()

// Each product's own words; Market AI's are as they were before the CRM assistant was separated.
const COPY = {
	market: {
		title: 'Market AI',
		subtitle: 'Research Dubai property market data, transactions, rents and projects.',
		empty: 'Ask Market AI.',
		emptyHint: 'Ask about Dubai transactions, rents, areas, projects or listings.',
		starters: [
			{
				label: 'Dubai Marina 2BR rents',
				prompt:
					'What was the median annual rent for 2-bedroom apartments in Dubai Marina last month?'
			},
			{ label: 'Recent Dubai sales', prompt: 'Summarize recent Dubai property sales by area.' },
			{
				label: 'Compare area prices',
				prompt: 'Compare current sale prices in Dubai Marina and JVC.'
			}
		],
		placeholder: 'Ask anything about Dubai real estate...',
		speaker: 'Vitevue AI'
	},
	crm: {
		title: 'CRM Operations Assistant',
		subtitle: 'Ask about your CRM records and teams. Changes require your confirmation.',
		empty: 'Ask your CRM assistant.',
		emptyHint:
			'Ask about your CRM leads, teams, owner imports and follow-ups, or prepare a change for your confirmation.',
		starters: [
			{ label: 'My CRM pipeline', prompt: 'Summarize my CRM leads by status.' },
			{
				label: 'My follow-ups due',
				prompt: 'Which of my CRM leads have follow-ups due today or earlier?'
			},
			{
				label: 'My CRM teams',
				prompt: 'Which teams are in my organization, with their managers and agents?'
			}
		],
		placeholder: 'Ask about your CRM records or request a change...',
		speaker: 'CRM assistant'
	}
} as const
const copy = $derived(COPY[assistant])

let talking = $state(false)
const showMic = $derived(voice && voiceSupported)

function startConversationWithPrompt(prompt: string) {
	inputValue = prompt
	handleSubmit()
}

interface DisplayMessage {
	id: string
	role: string
	content: string
	artifacts?: ChatArtifact[]
	actionIds?: string[]
}

let inputValue = $state('')
let messages = $state<DisplayMessage[]>([])
let streamController: { close: () => void } | null = $state(null)
// The one transient status of a running turn; tool progress never enters the transcript.
let workingStatus = $state<string | null>(null)
let error = $state<string | null>(null)
let textareaRef = $state<HTMLTextAreaElement>()
let messagesEndRef = $state<HTMLDivElement>()
let activeStreamConversationId: number | null = $state(null)
let tokenLimitModalOpen = $state(false)
// The message to send again when the failure says retrying is safe.
let retryText = $state<string | null>(null)
// The connection broke mid-turn: the server may still be answering, so sending is held until
// the conversation has been reloaded (a second send would only be refused as busy).
let awaitingReload = $state(false)
const RELOAD_AFTER_INTERRUPTION_MS = [5_000, 20_000, 60_000]
let olderMessages = $state<MessageResponse[]>([])
let loadingOlder = $state(false)
let hasOlder = $state(true)
let suppressScroll = false
let latestLoadedMessages: MessageResponse[] = []
let localMessageSequence = 0
const queryClient = useQueryClient()
const messagesQuery = createQuery(() => chatQueries.messages(conversationId, 100, assistant))
let loading = $derived(messagesQuery.isLoading)
let displayError = $derived(error ?? (messagesQuery.isError ? 'Failed to load messages' : null))
const scrollSignal = $derived(
	`${messages.length}:${messages.at(-1)?.content.length ?? 0}:${messages.at(-1)?.artifacts?.length ?? 0}:${workingStatus}:${streamController ? 'streaming' : 'idle'}`
)

function toDisplayMessages(loadedMessages: MessageResponse[]): DisplayMessage[] {
	return loadedMessages.map((m) => ({
		id: String(m.id),
		role: m.role,
		content: m.content,
		artifacts: artifactsFromMessage(m),
		actionIds: actionsFromMessage(m)
	}))
}

function nextLocalMessageId(role: string): string {
	localMessageSequence += 1
	return `local:${role}:${Date.now()}:${localMessageSequence}`
}

function artifactSignature(artifacts?: ChatArtifact[]): string {
	return (artifacts ?? [])
		.map((artifact) => `${artifact.id}:${artifact.status}:${artifactSortValue(artifact)}`)
		.join('|')
}

function messagesHaveSameVisibleContent(
	currentMessages: DisplayMessage[],
	nextMessages: DisplayMessage[]
): boolean {
	if (currentMessages.length !== nextMessages.length) return false

	return currentMessages.every((message, index) => {
		const nextMessage = nextMessages[index]
		return (
			message.role === nextMessage.role &&
			message.content === nextMessage.content &&
			artifactSignature(message.artifacts) === artifactSignature(nextMessage.artifacts) &&
			(message.actionIds ?? []).join(',') === (nextMessage.actionIds ?? []).join(',')
		)
	})
}

function preserveVisibleMessageIds(nextMessages: DisplayMessage[]): DisplayMessage[] {
	const reused = new Set<string>()
	return nextMessages.map((message) => {
		const currentMessage =
			messages.find((current) => current.id === message.id) ??
			messages.find(
				(current) =>
					!reused.has(current.id) &&
					current.id.startsWith('local:') &&
					current.role === message.role &&
					current.content === message.content
			)
		if (currentMessage && currentMessage.role === message.role) {
			reused.add(currentMessage.id)
			return { ...message, id: currentMessage.id }
		}
		return message
	})
}

function replaceMessagesIfChanged(nextMessages: DisplayMessage[]) {
	if (messagesHaveSameVisibleContent(messages, nextMessages)) return
	messages = preserveVisibleMessageIds(nextMessages)
}

function actionsFromMessage(message: MessageResponse): string[] {
	const metadata = message.meta_data as { actions?: unknown[] } | null | undefined
	return (Array.isArray(metadata?.actions) ? metadata.actions : []).flatMap((action) =>
		typeof action === 'object' && action !== null && 'id' in action && typeof action.id === 'string'
			? [action.id]
			: []
	)
}

async function loadOlderMessages() {
	const id = conversationId
	const oldest = olderMessages[0] ?? messagesQuery.data?.[0]
	if (!id || !oldest || loadingOlder) return
	loadingOlder = true
	try {
		const older = await chat.getMessages(id, { before_id: oldest.id, assistant })
		if (id !== conversationId) return
		suppressScroll = true
		olderMessages = [...older, ...olderMessages]
		hasOlder = older.length === 100
	} catch {
		error = 'Could not load older messages. Please try again.'
	} finally {
		loadingOlder = false
	}
}

function artifactsFromMessage(message: MessageResponse): ChatArtifact[] | undefined {
	const metadata = message.meta_data as { artifacts?: unknown[] } | null | undefined
	if (!Array.isArray(metadata?.artifacts)) return undefined
	const artifacts = metadata.artifacts.filter(isChatArtifact)
	if (artifacts.length === 0) return undefined

	return artifacts.sort((a, b) => artifactSortValue(a) - artifactSortValue(b))
}

function mergeArtifact(artifacts: ChatArtifact[], artifact: ChatArtifact): ChatArtifact[] {
	return [...artifacts.filter((item) => item.id !== artifact.id), artifact].sort(
		(a, b) => artifactSortValue(a) - artifactSortValue(b)
	)
}

// Load messages when conversation changes
let previousConversationId = $state<number | null>(null)

$effect(() => {
	if (conversationId !== previousConversationId) {
		// Cancel any active stream when switching conversations
		if (streamController && activeStreamConversationId !== conversationId) {
			streamController.close()
			streamController = null
			activeStreamConversationId = null
		}

		messages = []
		olderMessages = []
		latestLoadedMessages = []
		hasOlder = true
		error = null

		previousConversationId = conversationId
	}
})

$effect(() => {
	const loadedMessages = messagesQuery.data
	if (!conversationId || !loadedMessages || activeStreamConversationId === conversationId) return
	// Keep the boundary messages when a refreshed newest page moves forward.
	if (olderMessages.length > 0 && latestLoadedMessages !== loadedMessages) {
		const knownIds = new Set([...olderMessages, ...loadedMessages].map((message) => message.id))
		const retained = latestLoadedMessages.filter((message) => !knownIds.has(message.id))
		if (retained.length > 0) olderMessages = [...olderMessages, ...retained]
	}
	latestLoadedMessages = loadedMessages
	replaceMessagesIfChanged(toDisplayMessages([...olderMessages, ...loadedMessages]))
})

// Auto-scroll to bottom when messages change
$effect(() => {
	scrollSignal
	if (suppressScroll) {
		suppressScroll = false
		return
	}
	if (messages.length > 0 && messagesEndRef) {
		setTimeout(() => {
			messagesEndRef?.scrollIntoView({ behavior: streamController ? 'auto' : 'smooth' })
		}, 100)
	}
})

// Auto-send initial message when navigating from dashboard
$effect(() => {
	if (autoSend && initialMessage && conversationId && !loading && !streamController) {
		// Set the input value to the initial message
		inputValue = initialMessage

		// Trigger send after a brief delay for smooth UX
		setTimeout(() => {
			handleSubmit()
			onMessageSent()
		}, 300)
	}
})

async function retryLoadMessages() {
	error = null
	await messagesQuery.refetch()
}

async function refreshMessagesAfterStream(conversationIdToRefresh: number) {
	try {
		const loadedMessages = await chat.getMessages(conversationIdToRefresh, { assistant })
		queryClient.setQueryData(
			chatKeys.messages(conversationIdToRefresh, 100, assistant),
			loadedMessages
		)
		if (conversationId === conversationIdToRefresh) {
			replaceMessagesIfChanged(toDisplayMessages([...olderMessages, ...loadedMessages]))
		}
	} catch (err) {
		console.error('Failed to refresh streamed messages:', err)
	}
}

function dropEmptyAnswer() {
	const last = messages.at(-1)
	if (
		last?.role === 'assistant' &&
		!last.content &&
		!last.artifacts?.length &&
		!last.actionIds?.length
	) {
		messages = messages.slice(0, -1)
	}
}

function reloadAfterInterruption(id: number, attempt = 0) {
	awaitingReload = true
	setTimeout(() => {
		void refreshMessagesAfterStream(id).finally(() => {
			const answered = conversationId === id && messages.at(-1)?.role === 'assistant'
			if (answered || attempt + 1 >= RELOAD_AFTER_INTERRUPTION_MS.length || conversationId !== id) {
				awaitingReload = false
				if (activeStreamConversationId === id) activeStreamConversationId = null
				if (answered) error = null
				return
			}
			reloadAfterInterruption(id, attempt + 1)
		})
	}, RELOAD_AFTER_INTERRUPTION_MS[attempt])
}

async function handleSubmit() {
	const text = inputValue.trim()
	if (!text || !conversationId || awaitingReload) return
	error = null
	retryText = null

	if (streamController) streamController.close()

	// Store the conversation ID for this stream
	const streamConversationId = conversationId
	activeStreamConversationId = streamConversationId

	messages = [...messages, { id: nextLocalMessageId('user'), role: 'user', content: text }]
	inputValue = ''
	if (textareaRef) textareaRef.style.height = 'auto'

	// Start streaming
	let turn: TurnView = { answer: '', status: null }
	let currentArtifacts: ChatArtifact[] = []

	streamController = await chat.sendMessage(
		streamConversationId,
		text,
		(rawChunk) => {
			// Only update messages if we're still viewing the same conversation
			if (conversationId !== streamConversationId) {
				return
			}

			try {
				// Parse SSE data
				const data = JSON.parse(rawChunk)
				turn = applyTurnEvent(turn, data)
				workingStatus = turn.status

				if (data.type === 'thinking') {
					if (messages[messages.length - 1]?.role !== 'assistant') {
						messages = [
							...messages,
							{ id: nextLocalMessageId('assistant'), role: 'assistant', content: '' }
						]
					}
				} else if (data.type === 'content') {
					updateLastMessage('assistant', turn.answer, currentArtifacts)
				} else if (
					(data.type === 'artifact_opened' || data.type === 'artifact_updated') &&
					isChatArtifact(data.artifact)
				) {
					currentArtifacts = mergeArtifact(currentArtifacts, data.artifact)
					updateLastMessage('assistant', turn.answer, currentArtifacts)
				} else if (data.type === 'action_proposed' && typeof data.action?.id === 'string') {
					updateLastMessage('assistant', turn.answer, currentArtifacts)
					const last = messages[messages.length - 1]
					last.actionIds = [...new Set([...(last.actionIds ?? []), data.action.id])]
					messages = [...messages]
				} else if (data.type === 'done') {
					streamController = null
					void queryClient.invalidateQueries({
						queryKey: chatKeys.conversations(assistant)
					})
					void refreshMessagesAfterStream(streamConversationId).finally(() => {
						if (activeStreamConversationId === streamConversationId) {
							activeStreamConversationId = null
						}
					})
					setTimeout(() => textareaRef?.focus(), 100)
				} else if (data.type === 'error') {
					// A failure is not an empty answer: drop the placeholder and say what happened.
					const failure = describeChatError(data)
					console.error('Stream error:', data.code ?? data.error)
					dropEmptyAnswer()
					if (failure.dailyLimit) tokenLimitModalOpen = true
					error = failure.message
					retryText = failure.retry ? text : null
					streamController = null
					if (failure.reloadConversation) {
						reloadAfterInterruption(streamConversationId)
					} else {
						activeStreamConversationId = null
					}
				}
			} catch (e) {
				console.error('Failed to parse chunk:', rawChunk, e)
			}
		},
		assistant
	)
}

function updateLastMessage(role: string, content: string, artifacts?: ChatArtifact[]) {
	const lastMsg = messages[messages.length - 1]
	const nextArtifacts =
		artifacts && artifacts.length > 0
			? [...artifacts]
			: lastMsg?.role === role
				? lastMsg.artifacts
				: undefined
	if (lastMsg?.role === role) {
		messages[messages.length - 1] = {
			id: lastMsg.id,
			role,
			content,
			artifacts: nextArtifacts,
			actionIds: lastMsg.actionIds
		}
		messages = [...messages]
	} else {
		messages = [
			...messages,
			{
				id: nextLocalMessageId(role),
				role,
				content,
				artifacts: nextArtifacts
			}
		]
	}
}

function autoResizeTextarea() {
	if (textareaRef) {
		textareaRef.style.height = 'auto'
		const newHeight = Math.min(textareaRef.scrollHeight, 200)
		textareaRef.style.height = `${newHeight}px`
	}
}

function stopStreaming() {
	streamController?.close()
	streamController = null
	activeStreamConversationId = null
	workingStatus = null
}
</script>

<div class="flex h-full min-h-0 flex-col bg-card">
	{#if showHeader}
		<div
			class="flex items-start justify-between gap-4 border-b border-border bg-card px-5 py-4"
		>
			<div>
				<div class="flex items-center gap-2">
					<img src="/icon.svg" alt="" class="h-3.5 w-3.5" />
					<h1 class="text-sm font-semibold text-fg-1">{copy.title}</h1>
				</div>
				<p class="mt-1 text-xs text-fg-4">
					{copy.subtitle}
				</p>
			</div>
			<div
				class="mt-0.5 inline-flex items-center gap-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-success"
			>
				<span
					class="h-1.5 w-1.5 rounded-full bg-success shadow-[0_0_0_3px_rgba(17,122,72,0.18)]"
				></span>
				Live
			</div>
		</div>
	{/if}

	<!-- Messages -->
	<div class="flex-1 space-y-3 overflow-y-auto bg-card p-5">
		{#if loading}
			<div class="flex h-full items-center justify-center">
				<div class="text-center">
					<div
						class="mb-3 inline-block h-8 w-8 animate-spin rounded-full border-2 border-border border-t-fg-1"
					></div>
					<p class="text-sm font-medium text-fg-3">Loading messages...</p>
				</div>
			</div>
		{:else if displayError && messages.length === 0}
			<div class="flex h-full items-center justify-center">
				<div class="max-w-md text-center">
					<div
						class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-error-bg"
					>
						<svg class="h-6 w-6 text-error" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
							/>
						</svg>
					</div>
					<p class="mb-4 text-sm text-error">{displayError}</p>
					<button
						onclick={() => void retryLoadMessages()}
						class="rounded-md bg-error px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
					>
						Try again
					</button>
				</div>
			</div>
		{:else if messages.length === 0 && conversationId}
			{#if autoSend && initialMessage}
				<!-- Don't show empty state if we're about to auto-send -->
				<div class="flex h-full items-center justify-center">
					<div class="text-center">
						<div
							class="mb-3 inline-block h-8 w-8 animate-spin rounded-full border-2 border-border border-t-fg-1"
						></div>
						<p class="text-sm font-medium text-fg-3">Starting conversation...</p>
					</div>
				</div>
			{:else}
				<div
					class="flex h-full items-center justify-center"
					in:fade={{ duration: 300, easing: cubicOut }}
				>
					<div class="w-full max-w-2xl text-center">
						<div
							class="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-card"
							in:fly={{ y: -20, duration: 500, delay: 100, easing: cubicOut }}
						>
							<img src="/icon.svg" alt="" class="h-5 w-5" />
						</div>
						<h3
							class="mb-2 font-display text-3xl font-normal tracking-[var(--tracking-display)] text-fg-1"
							in:fly={{ y: 20, duration: 500, delay: 200, easing: cubicOut }}
						>
							{copy.empty}
						</h3>
						<p
							class="mx-auto mb-6 max-w-md text-sm leading-6 text-fg-3"
							in:fly={{ y: 20, duration: 500, delay: 300, easing: cubicOut }}
						>
							{copy.emptyHint}
						</p>
						<div
							class="mx-auto grid max-w-xl grid-cols-1 gap-2 text-[13px] sm:grid-cols-3"
							in:fly={{ y: 20, duration: 500, delay: 400, easing: cubicOut }}
						>
			{#each copy.starters as starter (starter.label)}
				<button
					onclick={() => startConversationWithPrompt(starter.prompt)}
					class="rounded-md border border-border bg-card px-3 py-2.5 text-left leading-5 text-fg-2 transition-colors hover:border-strong hover:bg-panel"
				>
					<span class="mr-1 text-fg-5">→</span>
					{starter.label}
				</button>
			{/each}
						</div>
					</div>
				</div>
			{/if}
		{:else if !conversationId}
			<div
				class="flex h-full items-center justify-center"
				in:fade={{ duration: 300, easing: cubicOut }}
			>
				<div class="max-w-md text-center">
					<div
						class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-card"
						in:fly={{ y: -20, duration: 500, easing: cubicOut }}
					>
						<img src="/icon.svg" alt="" class="h-5 w-5" />
					</div>
					<p
						class="text-sm font-medium text-fg-3"
						in:fly={{ y: 20, duration: 500, delay: 100, easing: cubicOut }}
					>
						Select or create a conversation to start.
					</p>
				</div>
			</div>
		{:else}
			{#if hasOlder && (olderMessages.length > 0 || (messagesQuery.data?.length ?? 0) >= 100)}
				<button type="button" class="ui-button px-3 py-2 text-xs" disabled={loadingOlder} onclick={loadOlderMessages}>
					{loadingOlder ? 'Loading older messages…' : 'Load older messages'}
				</button>
			{/if}
			{#each messages as msg, i (msg.id)}
				<div
					class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}"
					in:fly={{ y: 10, duration: 250, delay: Math.min(i * 30, 200), easing: cubicOut }}
				>
					<div
						class="{msg.role === 'assistant' && msg.artifacts?.length
							? 'w-[min(860px,94%)]'
							: 'max-w-[min(720px,88%)]'} rounded-md px-3.5 py-2.5 text-[13px] leading-[1.55] {msg.role ===
						'user'
							? 'bg-navy text-bone'
							: msg.artifacts?.length
								? 'bg-transparent text-fg-2'
								: 'border border-border bg-panel text-fg-2'}"
					>
						{#if workingStatus && i === messages.length - 1 && msg.role === 'assistant' && !msg.content && !msg.artifacts?.length}
							<div class="flex items-center gap-2 text-fg-5">
								<div class="flex gap-1 items-center">
									<div
										class="w-1.5 h-1.5 bg-fg-5 rounded-full animate-bounce"
										style="animation-delay: 0ms"
									></div>
									<div
										class="w-1.5 h-1.5 bg-fg-5 rounded-full animate-bounce"
										style="animation-delay: 150ms"
									></div>
									<div
										class="w-1.5 h-1.5 bg-fg-5 rounded-full animate-bounce"
										style="animation-delay: 300ms"
									></div>
								</div>
								<span class="text-sm" role="status">{workingStatus}</span>
							</div>
						{:else if msg.role === 'assistant'}
							<div
								class="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-fg-4"
								>
									{copy.speaker}
								</div>
									{#if msg.artifacts?.length}
										<div class="{msg.content ? 'mb-3' : ''} space-y-3">
											{#each msg.artifacts as artifact (artifact.id)}
												<ChatArtifactBubble {artifact} />
											{/each}
										</div>
									{/if}
									{#if msg.actionIds?.length}
										<div class="mb-3 space-y-3">
											{#each msg.actionIds as actionId (actionId)}
												<ChatActionCard {actionId} />
											{/each}
										</div>
									{/if}
									{#if msg.content}
										<div
											class="leading-relaxed [&_p]:mb-2 [&_p:last-child]:mb-0 [&_strong]:font-semibold [&_em]:italic [&_a]:text-primary-light [&_a]:underline [&_a:hover]:text-fg-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-2 [&_li]:mb-0.5 [&_blockquote]:border-l-4 [&_blockquote]:border-strong [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-fg-3 [&_blockquote]:my-2 [&_code]:bg-panel [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&_code]:font-mono [&_pre]:bg-panel [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:overflow-x-auto [&_pre]:my-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-2 [&_table]:block [&_table]:max-w-full [&_table]:overflow-x-auto [&_table]:border-collapse [&_table]:text-sm [&_th]:border [&_th]:border-border [&_th]:bg-panel [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_th]:font-semibold [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_td]:align-top"
								>
									{@html renderMarkdown(msg.content)}
								</div>
							{/if}
							{:else}
								<div class="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
							{/if}
						</div>
				</div>
			{/each}
			<div bind:this={messagesEndRef}></div>
		{/if}
	</div>

	<!-- Input Area -->
	<div class="border-t border-border bg-card p-4">
		{#if displayError && messages.length > 0}
			<div
				class="mb-4 flex items-center gap-2 rounded-lg border border-[rgba(163,36,36,0.2)] bg-error-bg p-3 text-sm text-error"
				in:fly={{ y: -10, duration: 300, easing: cubicOut }}
			>
				<svg class="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
					<path
						fill-rule="evenodd"
						d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
						clip-rule="evenodd"
					/>
				</svg>
				<span class="flex-1">{displayError}</span>
				{#if retryText && error}
					<button
						type="button"
						class="shrink-0 rounded px-2 py-1 text-xs font-medium underline hover:opacity-80"
						onclick={() => {
							inputValue = retryText ?? ''
							void handleSubmit()
						}}
					>
						Try again
					</button>
				{/if}
			</div>
		{/if}

		{#if talking}
			<VoicePanel
				onsend={(text) => {
					talking = false
					inputValue = text
					handleSubmit()
				}}
				onclose={() => (talking = false)}
			/>
		{/if}

		<div class="relative">
			{#if showMic}
				<button
					type="button"
					onclick={() => (talking = true)}
					disabled={!conversationId || streamController !== null}
					class="absolute right-11 top-1.5 flex h-8 w-8 items-center justify-center rounded text-fg-3 transition-colors hover:bg-panel hover:text-fg-1 disabled:cursor-not-allowed disabled:text-fg-5 disabled:hover:bg-transparent"
					aria-label="Speak to the assistant"
					title="Speak to the assistant"
				>
					<Mic size={15} />
				</button>
			{/if}
			<textarea
				bind:this={textareaRef}
				bind:value={inputValue}
				oninput={autoResizeTextarea}
				onkeydown={(e) => {
					if (e.key === 'Enter' && !e.shiftKey) {
						e.preventDefault();
						handleSubmit();
					}
				}}
				placeholder={conversationId
					? copy.placeholder
					: 'Select or create a conversation first'}
				class="min-h-11 w-full resize-none rounded-md border border-focus bg-card py-3 pl-4 {showMic ? 'pr-24' : 'pr-14'} text-[13px] leading-5 text-fg-1 placeholder:text-fg-5 focus:outline-none focus:ring-2 focus:ring-navy/10"
				rows="1"
				readonly={!conversationId || streamController !== null}
				style="max-height: 180px;"
			></textarea>

			{#if streamController}
				<button
					onclick={stopStreaming}
					class="absolute right-1.5 top-1.5 flex h-8 w-8 items-center justify-center rounded bg-error text-white transition-opacity hover:opacity-90"
					aria-label="Stop streaming"
				>
					<svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 20 20">
						<path
							fill-rule="evenodd"
							d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z"
							clip-rule="evenodd"
						/>
					</svg>
				</button>
			{:else}
				<button
					onclick={handleSubmit}
					disabled={!inputValue.trim() || !conversationId || awaitingReload}
					class="absolute right-1.5 top-1.5 flex h-8 w-8 items-center justify-center rounded transition-colors {inputValue.trim() &&
					conversationId
						? 'bg-navy text-bone hover:bg-primary-light'
						: 'cursor-not-allowed bg-panel text-fg-5'}"
					aria-label="Send message"
				>
					<svg class="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
						<path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
					</svg>
				</button>
			{/if}
		</div>
	</div>
</div>

<!-- Token Limit Exceeded Modal -->
<ConfirmModal
	open={tokenLimitModalOpen}
	title="Daily token limit exceeded"
	message="You have reached your daily token usage limit. Please try again tomorrow or contact your organization owner to increase your limit."
	confirmText="OK"
	confirmVariant="primary"
	onConfirm={() => (tokenLimitModalOpen = false)}
	onCancel={() => (tokenLimitModalOpen = false)}
/>
