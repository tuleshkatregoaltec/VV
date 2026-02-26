<script lang="ts">
	import { browser } from '$app/environment';
	import { feasibility } from '$lib/api/feasibility';
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	const SANITIZE_CONFIG = {
		ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'ul', 'ol', 'li', 'blockquote', 'code', 'span'],
		ALLOWED_ATTR: [],
	};

	function renderMarkdown(content: string): string {
		if (!browser) return content;
		return DOMPurify.sanitize(marked.parse(content) as string, SANITIZE_CONFIG);
	}

	interface ChatMessage {
		role: 'user' | 'assistant';
		content: string;
	}

	let expanded = $state(false);
	let inputValue = $state('');
	let messages = $state<ChatMessage[]>([]);
	let isStreaming = $state(false);
	let streamController: { close: () => void } | null = null;
	let messagesEnd: HTMLDivElement | undefined = $state();

	function scrollToBottom() {
		setTimeout(() => messagesEnd?.scrollIntoView({ behavior: 'smooth' }), 50);
	}

	async function sendMessage() {
		const content = inputValue.trim();
		if (!content || isStreaming) return;
		inputValue = '';
		messages = [...messages, { role: 'user', content }];
		messages = [...messages, { role: 'assistant', content: '' }];
		isStreaming = true;
		scrollToBottom();

		const apiMessages = messages.slice(0, -1).map((m) => ({
			role: m.role,
			content: m.content,
		}));

		streamController = await feasibility.streamChat(apiMessages, {
			area: feasibilityStore.area,
			plot: feasibilityStore.plot,
			config: feasibilityStore.config,
		}, (raw) => {
			try {
				const parsed = JSON.parse(raw);
				if (parsed.type === 'text') {
					messages = messages.map((m, i) =>
						i === messages.length - 1 ? { ...m, content: m.content + parsed.content } : m
					);
					scrollToBottom();
				} else if (parsed.type === 'action') {
					feasibilityStore.applyLLMAction(parsed.action, parsed.payload);
				} else if (parsed.type === 'done' || parsed.type === 'error') {
					isStreaming = false;
					streamController = null;
				}
			} catch {
				// ignore non-JSON chunks
			}
		});
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}
</script>

<!-- Fixed bottom-right chat bubble -->
<div class="fixed bottom-6 right-6 z-40 flex flex-col items-end gap-3">
	<!-- Chat panel -->
	{#if expanded}
		<div
			class="w-80 bg-white rounded-2xl shadow-xl border border-slate-200 flex flex-col overflow-hidden"
			style="height: 420px;"
		>
			<!-- Header -->
			<div class="flex items-center justify-between px-4 py-3 bg-teal-600 text-white flex-shrink-0">
				<div class="flex items-center gap-2">
					<div class="w-2 h-2 rounded-full bg-emerald-300"></div>
					<span class="text-sm font-medium">Feasibility Assistant</span>
				</div>
				<button type="button" onclick={() => (expanded = false)} class="text-teal-200 hover:text-white">
					<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
					</svg>
				</button>
			</div>

			<!-- Messages -->
			<div class="flex-1 overflow-y-auto px-3 py-3 space-y-3">
				{#if messages.length === 0}
					<div class="text-center py-6">
						<p class="text-xs text-slate-400">Ask me about market prices, unit mix, or GDV assumptions.</p>
					</div>
				{/if}
				{#each messages as msg}
					<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
						<div
							class="max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed
								{msg.role === 'user'
									? 'bg-teal-600 text-white'
									: 'bg-slate-100 text-slate-800 prose prose-sm max-w-none'}"
						>
							{#if msg.role === 'assistant' && msg.content}
								<!-- eslint-disable-next-line svelte/no-at-html-tags -->
								{@html renderMarkdown(msg.content)}
							{:else if msg.role === 'assistant' && isStreaming}
								<span class="inline-block w-2 h-3 bg-slate-400 rounded-sm animate-pulse"></span>
							{:else}
								{msg.content}
							{/if}
						</div>
					</div>
				{/each}
				<div bind:this={messagesEnd}></div>
			</div>

			<!-- Input -->
			<div class="flex items-end gap-2 px-3 pb-3 flex-shrink-0">
				<textarea
					class="flex-1 px-3 py-2 text-xs rounded-xl border border-slate-200 text-slate-800 placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-teal-400 transition-all"
					placeholder="Ask anything..."
					rows="2"
					bind:value={inputValue}
					onkeydown={handleKeydown}
					disabled={isStreaming}
				></textarea>
				<button
					type="button"
					class="flex-shrink-0 w-8 h-8 rounded-xl bg-teal-600 text-white flex items-center justify-center hover:bg-teal-700 disabled:opacity-50 transition-colors"
					onclick={sendMessage}
					disabled={isStreaming || !inputValue.trim()}
				>
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
					</svg>
				</button>
			</div>
		</div>
	{/if}

	<!-- Bubble toggle -->
	<button
		type="button"
		class="w-12 h-12 rounded-full bg-teal-600 text-white shadow-lg flex items-center justify-center hover:bg-teal-700 transition-all hover:scale-105"
		onclick={() => (expanded = !expanded)}
		title="Feasibility Assistant"
	>
		{#if expanded}
			<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
			</svg>
		{:else}
			<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
			</svg>
		{/if}
	</button>
</div>
