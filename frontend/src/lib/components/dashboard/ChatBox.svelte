<script lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { cubicOut } from 'svelte/easing'
import { fade, fly } from 'svelte/transition'
import { browser } from '$app/environment'
import { chat, type MessageResponse } from '$lib/api/chat'
import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte'

// Add target="_blank" rel="noopener noreferrer" to all links
marked.use({
	renderer: {
		link({ href, title, text }: any) {
			const titleAttr = title ? ` title="${title}"` : ''
			return `<a href="${href}"${titleAttr} target="_blank" rel="noopener noreferrer">${text}</a>`
		}
	}
})

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
		'span'
	],
	ALLOWED_ATTR: ['href', 'title', 'target', 'rel']
}

function renderMarkdown(content: string): string {
	if (!browser) return content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
	return DOMPurify.sanitize(marked.parse(content) as string, SANITIZE_CONFIG)
}

let {
	conversationId = $bindable(null),
	initialMessage = null,
	autoSend = false,
	showHeader = true,
	onMessageSent = () => {}
}: {
	conversationId: number | null
	initialMessage?: string | null
	autoSend?: boolean
	showHeader?: boolean
	onMessageSent?: () => void
} = $props()

function startConversationWithPrompt(prompt: string) {
	inputValue = prompt
	handleSubmit()
}

interface DisplayMessage {
	role: string
	content: string
	toolCalls?: string[]
}

let inputValue = $state('')
let messages = $state<DisplayMessage[]>([])
let streamController: { close: () => void } | null = $state(null)
let isThinking = $state(false)
let loading = $state(false)
let error = $state<string | null>(null)
let textareaRef = $state<HTMLTextAreaElement>()
let messagesEndRef = $state<HTMLDivElement>()
let activeStreamConversationId: number | null = $state(null)
let tokenLimitModalOpen = $state(false)

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

		if (conversationId) {
			loadMessages()
		} else {
			messages = []
		}

		previousConversationId = conversationId
	}
})

// Auto-scroll to bottom when messages change
$effect(() => {
	if (messages.length > 0 && messagesEndRef) {
		setTimeout(() => {
			messagesEndRef?.scrollIntoView({ behavior: 'smooth' })
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

async function loadMessages() {
	if (!conversationId) return
	loading = true
	error = null
	try {
		const msgs = await chat.getMessages(conversationId)
		messages = msgs.map((m: MessageResponse) => ({
			role: m.role,
			content: m.content,
			toolCalls: []
		}))
	} catch (err) {
		console.error('Failed to load messages:', err)
		error = 'Failed to load messages'
	} finally {
		loading = false
	}
}

async function handleSubmit() {
	const text = inputValue.trim()
	if (!text || !conversationId) return

	if (streamController) streamController.close()

	// Store the conversation ID for this stream
	const streamConversationId = conversationId
	activeStreamConversationId = streamConversationId

	// Add user message
	messages = [...messages, { role: 'user', content: text }]
	inputValue = ''
	if (textareaRef) textareaRef.style.height = 'auto'

	// Start streaming
	let currentAssistantMessage = ''
	let currentToolCalls: string[] = []

	streamController = await chat.sendMessage(streamConversationId, text, (rawChunk) => {
		// Only update messages if we're still viewing the same conversation
		if (conversationId !== streamConversationId) {
			return
		}

		try {
			// Parse SSE data
			const data = JSON.parse(rawChunk)

			if (data.type === 'thinking') {
				isThinking = true
				if (messages[messages.length - 1]?.role !== 'assistant') {
					messages = [...messages, { role: 'assistant', content: '' }]
				}
			} else if (data.type === 'content') {
				isThinking = false
				currentAssistantMessage += data.content
				updateLastMessage('assistant', currentAssistantMessage, currentToolCalls)
			} else if (data.type === 'tool_call_start') {
				currentToolCalls.push(`Calling ${data.tool}...`)
				updateLastMessage('assistant', currentAssistantMessage, currentToolCalls)
			} else if (data.type === 'tool_call_result') {
				const cached = data.cached ? ' (cached)' : ''
				currentToolCalls[currentToolCalls.length - 1] = `✓ ${data.tool}${cached}`
				updateLastMessage('assistant', currentAssistantMessage, currentToolCalls)
			} else if (data.type === 'done') {
				isThinking = false
				streamController = null
				activeStreamConversationId = null
				setTimeout(() => textareaRef?.focus(), 100)
			} else if (data.type === 'error') {
				console.error('Stream error:', data.error)
				isThinking = false
				if (data.error === 'token_limit_exceeded') {
					tokenLimitModalOpen = true
				} else {
					error = `Error: ${data.error}`
				}
				streamController = null
				activeStreamConversationId = null
			}
		} catch (e) {
			console.error('Failed to parse chunk:', rawChunk, e)
		}
	})
}

function updateLastMessage(role: string, content: string, toolCalls: string[]) {
	const lastMsg = messages[messages.length - 1]
	if (lastMsg?.role === role) {
		messages[messages.length - 1] = {
			role,
			content,
			toolCalls: toolCalls.length > 0 ? [...toolCalls] : undefined
		}
		messages = [...messages]
	} else {
		messages = [
			...messages,
			{ role, content, toolCalls: toolCalls.length > 0 ? [...toolCalls] : undefined }
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
	isThinking = false
}
</script>

<div class="flex h-full min-h-0 flex-col bg-white">
	{#if showHeader}
		<div
			class="flex items-start justify-between gap-4 border-b border-border bg-white px-5 py-4"
		>
			<div>
				<div class="flex items-center gap-2">
					<img src="/icon.svg" alt="" class="h-3.5 w-3.5" />
					<h1 class="text-sm font-semibold text-fg-1">Vitevue AI</h1>
				</div>
				<p class="mt-1 text-xs text-fg-4">
					Ask about transactions, yields, pricing, projects, and feasibility context.
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
	<div class="flex-1 space-y-3 overflow-y-auto bg-white p-5">
		{#if loading}
			<div class="flex h-full items-center justify-center">
				<div class="text-center">
					<div
						class="mb-3 inline-block h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-navy"
					></div>
					<p class="text-sm font-medium text-fg-3">Loading messages...</p>
				</div>
			</div>
		{:else if error && messages.length === 0}
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
					<p class="mb-4 text-sm text-error">{error}</p>
					<button
						onclick={loadMessages}
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
							class="mb-3 inline-block h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-navy"
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
							class="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-white"
							in:fly={{ y: -20, duration: 500, delay: 100, easing: cubicOut }}
						>
							<img src="/icon.svg" alt="" class="h-5 w-5" />
						</div>
						<h3
							class="mb-2 font-display text-3xl font-normal tracking-[var(--tracking-display)] text-fg-1"
							in:fly={{ y: 20, duration: 500, delay: 200, easing: cubicOut }}
						>
							Ask Vitevue AI.
						</h3>
						<p
							class="mx-auto mb-6 max-w-md text-sm leading-6 text-fg-3"
							in:fly={{ y: 20, duration: 500, delay: 300, easing: cubicOut }}
						>
							Start with a market question, comp basket, pricing trend, or feasibility assumption.
						</p>
						<div
							class="mx-auto grid max-w-xl grid-cols-1 gap-2 text-[13px] sm:grid-cols-3"
							in:fly={{ y: 20, duration: 500, delay: 400, easing: cubicOut }}
						>
							<button
								onclick={() =>
									startConversationWithPrompt(
										'What changed in Dubai Marina 2BR yields this quarter?'
									)}
								class="rounded-md border border-slate-200 bg-white px-3 py-2.5 text-left leading-5 text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50"
							>
								<span class="mr-1 text-slate-400">→</span>
								Dubai Marina 2BR yields
							</button>
							<button
								onclick={() =>
									startConversationWithPrompt('Compare Dubai Marina pricing against JBR.')}
								class="rounded-md border border-slate-200 bg-white px-3 py-2.5 text-left leading-5 text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50"
							>
								<span class="mr-1 text-slate-400">→</span>
								Compare to JBR
							</button>
							<button
								onclick={() =>
									startConversationWithPrompt('Build a comp basket for Business Bay offices.')}
								class="rounded-md border border-slate-200 bg-white px-3 py-2.5 text-left leading-5 text-slate-700 transition-colors hover:border-slate-300 hover:bg-slate-50"
							>
								<span class="mr-1 text-slate-400">→</span>
								Build a comp basket
							</button>
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
						class="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-border bg-white"
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
			{#each messages as msg, i (i)}
				<div
					class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}"
					in:fly={{ y: 10, duration: 250, delay: Math.min(i * 30, 200), easing: cubicOut }}
				>
					<div
						class="max-w-[min(720px,88%)] rounded-md px-3.5 py-2.5 text-[13px] leading-[1.55] {msg.role === 'user'
							? 'bg-navy text-bone'
							: 'border border-slate-200 bg-slate-50 text-fg-2'}"
					>
						{#if isThinking && i === messages.length - 1 && msg.role === 'assistant' && !msg.content}
							<div class="flex items-center gap-2 text-slate-400">
								<div class="flex gap-1 items-center">
									<div
										class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"
										style="animation-delay: 0ms"
									></div>
									<div
										class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"
										style="animation-delay: 150ms"
									></div>
									<div
										class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce"
										style="animation-delay: 300ms"
									></div>
								</div>
								<span class="text-sm">Thinking...</span>
							</div>
						{:else if msg.role === 'assistant'}
							<div
								class="mb-1.5 font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-fg-4"
							>
								Vitevue AI
							</div>
							<div
								class="leading-relaxed [&_p]:mb-2 [&_p:last-child]:mb-0 [&_strong]:font-semibold [&_em]:italic [&_a]:text-primary-light [&_a]:underline [&_a:hover]:text-fg-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-2 [&_li]:mb-0.5 [&_blockquote]:border-l-4 [&_blockquote]:border-slate-300 [&_blockquote]:pl-3 [&_blockquote]:italic [&_blockquote]:text-slate-600 [&_blockquote]:my-2 [&_code]:bg-slate-100 [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-sm [&_code]:font-mono [&_pre]:bg-slate-100 [&_pre]:p-3 [&_pre]:rounded-lg [&_pre]:overflow-x-auto [&_pre]:my-2 [&_pre_code]:bg-transparent [&_pre_code]:p-0"
							>
								{@html renderMarkdown(msg.content)}
							</div>
						{:else}
							<div class="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
						{/if}
						{#if msg.toolCalls && msg.toolCalls.length > 0}
							<div
								class="mt-3 pt-3 border-t {msg.role === 'user'
									? 'border-slate-700'
									: 'border-slate-200'} text-xs space-y-2"
							>
								{#each msg.toolCalls as toolCall (toolCall)}
									<div
										class="flex items-center gap-2 {msg.role === 'user'
											? 'text-slate-300'
											: 'text-slate-600'}"
									>
										<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												stroke-width="2"
												d="M13 10V3L4 14h7v7l9-11h-7z"
											/>
										</svg>
										<span class="font-medium">{toolCall}</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{/each}
			<div bind:this={messagesEndRef}></div>
		{/if}
	</div>

	<!-- Input Area -->
	<div class="border-t border-slate-200 bg-white p-4">
		{#if error && messages.length > 0}
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
				<span>{error}</span>
			</div>
		{/if}

		<div class="relative">
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
					? 'Ask anything about Dubai real estate...'
					: 'Select or create a conversation first'}
				class="min-h-11 w-full resize-none rounded-md border border-navy bg-white py-3 pl-4 pr-14 text-[13px] leading-5 text-fg-1 placeholder:text-fg-5 focus:outline-none focus:ring-2 focus:ring-navy/10"
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
					disabled={!inputValue.trim() || !conversationId}
					class="absolute right-1.5 top-1.5 flex h-8 w-8 items-center justify-center rounded transition-colors {inputValue.trim() &&
					conversationId
						? 'bg-navy text-bone hover:bg-primary-light'
						: 'cursor-not-allowed bg-slate-200 text-slate-400'}"
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
