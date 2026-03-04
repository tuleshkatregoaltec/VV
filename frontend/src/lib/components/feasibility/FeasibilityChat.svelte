<script lang="ts">
	import { browser } from '$app/environment';
	import { feasibility } from '$lib/api/feasibility';
	import { feasibilityStore } from '$lib/stores/feasibility.svelte';
	import { researchPanelStore, type ResearchTab } from '$lib/stores/researchPanel.svelte';
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

	type MessageRole = 'user' | 'assistant' | 'system';

	interface ChatMessage {
		role: MessageRole;
		content: string; // for system: 'applied' | 'declined'
	}

	interface PendingAction {
		action: string;
		payload: unknown;
	}

	let inputValue = $state('');
	let messages = $state<ChatMessage[]>([]);
	let isStreaming = $state(false);
	let messagesEnd: HTMLDivElement | undefined = $state();
	let textarea: HTMLTextAreaElement | undefined = $state();
	let pendingActions = $state<PendingAction[]>([]);
	let historyJson = $state<string | null>(null);
	let lastAppliedMsgIndex = $state(-1);

	function fmtAssumptionVal(key: string, val: unknown): string {
		if (typeof val !== 'number') return String(val ?? '—');
		if (key === 'landCost') {
			if (val >= 1_000_000) return `AED ${(val / 1_000_000).toFixed(1)}M`;
			if (val >= 1_000) return `AED ${(val / 1_000).toFixed(0)}K`;
			return `AED ${val}`;
		}
		if (key === 'debtToCostRatio') return `${(val * 100).toFixed(0)}%`;
		if (key.endsWith('Pct')) return `${val}%`;
		if (key.toLowerCase().includes('month')) return `${val} mo`;
		return val.toLocaleString('en-AE', { maximumFractionDigits: 2 });
	}

	interface Change { key: string; before: string; after: string }

	function describeAction(pa: PendingAction): { title: string; changes: Change[] } {
		if (pa.action === 'set_price_per_sqm') {
			const payload = pa.payload as Record<string, number>;
			return {
				title: 'Update prices',
				changes: Object.entries(payload).map(([type, newPrice]) => ({
					key: type,
					before: `AED ${(feasibilityStore.config.pricePerSqm[type] ?? 0).toLocaleString()}/sqm`,
					after: `AED ${newPrice.toLocaleString()}/sqm`,
				})),
			};
		}
		if (pa.action === 'set_assumptions') {
			const patch = pa.payload as Record<string, unknown>;
			return {
				title: 'Update assumptions',
				changes: Object.entries(patch).map(([key, newVal]) => ({
					key,
					before: fmtAssumptionVal(key, (feasibilityStore.assumptions as Record<string, unknown>)[key]),
					after: fmtAssumptionVal(key, newVal),
				})),
			};
		}
		if (pa.action === 'set_buildings') {
			const b = pa.payload as Array<{ name: string }>;
			return { title: 'Reconfigure buildings', changes: [{ key: '', before: '', after: b.map((x) => x.name).join(', ') }] };
		}
		return { title: pa.action, changes: [] };
	}

	function acceptChanges() {
		feasibilityStore.takeUndoSnapshot();
		for (const pa of pendingActions) {
			feasibilityStore.applyLLMAction(pa.action, pa.payload);
		}
		pendingActions = [];
		messages = [...messages, { role: 'system', content: 'applied' }];
		lastAppliedMsgIndex = messages.length - 1;
		scrollToBottom();
	}

	function undoChanges() {
		feasibilityStore.undoLastChange();
		messages[lastAppliedMsgIndex] = { role: 'system', content: 'undone' };
		lastAppliedMsgIndex = -1;
		scrollToBottom();
	}

	function declineChanges() {
		pendingActions = [];
		messages = [...messages, { role: 'system', content: 'declined' }];
		scrollToBottom();
	}

	function scrollToBottom() {
		setTimeout(() => messagesEnd?.scrollIntoView({ behavior: 'smooth' }), 50);
	}

	function buildContext() {
		const s = feasibilityStore;
		return {
			area: s.area,
			plot: s.plot,
			config: s.config,
			assumptions: s.assumptions,
			derived: {
				totalUnits: s.totalUnits,
				totalSellableAreaSqm: Math.round(s.totalSellableAreaSqm),
				totalGDV: Math.round(s.totalGDV),
				totalBlendedGDV: Math.round(s.totalBlendedGDV),
				netRevenue: Math.round(s.netRevenue),
				hardConstructionCost: Math.round(s.hardCost),
				totalHardCost: Math.round(s.totalHardCost),
				totalSoftCost: Math.round(s.totalSoftCost),
				totalSalesCost: Math.round(s.totalSalesCost),
				totalFinanceCost: Math.round(s.totalFinanceCost),
				totalDevCost: Math.round(s.totalDevCost),
				equityRequired: Math.round(s.equityRequired),
				debtAmount: Math.round(s.debtAmount),
				grossProfit: Math.round(s.grossProfit),
				returnOnCost: +s.returnOnCost.toFixed(1),
				returnOnEquity: +s.returnOnEquity.toFixed(1),
				equityMultiple: +s.equityMultiple.toFixed(2),
				unleveredIRR: isNaN(s.unleveredIRR) ? null : +(s.unleveredIRR * 100).toFixed(1),
				leveredIRR: isNaN(s.leveredIRR) ? null : +(s.leveredIRR * 100).toFixed(1),
				peakFunding: Math.round(s.peakFunding),
				cashBreakevenQuarter: s.cashBreakevenQuarter,
				blendedPricePerSqm: Math.round(s.blendedPricePerSqm),
			},
		};
	}

	async function sendMessage() {
		const content = inputValue.trim();
		if (!content || isStreaming) return;
		inputValue = '';
		pendingActions = [];
		messages = [...messages, { role: 'user', content }];
		messages = [...messages, { role: 'assistant', content: '' }];
		isStreaming = true;
		scrollToBottom();

		// Exclude system messages from API history
		const apiMessages = messages
			.slice(0, -1)
			.filter((m) => m.role !== 'system')
			.map((m) => ({ role: m.role, content: m.content }));

		await feasibility.streamChat(apiMessages, buildContext(), historyJson, (raw) => {
			try {
				const parsed = JSON.parse(raw);
				if (parsed.type === 'text') {
					messages = messages.map((m, i) =>
						i === messages.length - 1 ? { ...m, content: m.content + parsed.content } : m
					);
					scrollToBottom();
				} else if (parsed.type === 'pending_action') {
					pendingActions = [...pendingActions, { action: parsed.action, payload: parsed.payload }];
				} else if (parsed.type === 'show_research') {
					researchPanelStore.setActiveTab(parsed.tab as ResearchTab);
					researchPanelStore.setAgentData(parsed.tab, parsed.data);
				} else if (parsed.type === 'done') {
					isStreaming = false;
					if (parsed.new_messages_json) historyJson = parsed.new_messages_json;
					if (!pendingActions.length) setTimeout(() => textarea?.focus(), 0);
				} else if (parsed.type === 'warning') {
					messages = [...messages, { role: 'system', content: parsed.content }];
					scrollToBottom();
				} else if (parsed.type === 'error') {
					isStreaming = false;
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

<div class="h-full flex flex-col bg-white border-l border-slate-200">
	<!-- Header -->
	<div class="flex items-center gap-2 px-4 py-3 border-b border-slate-200 flex-shrink-0 bg-white">
		<div class="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0"></div>
		<span class="text-sm font-semibold text-slate-800">Feasibility Assistant</span>
	</div>

	<!-- Messages -->
	<div class="flex-1 overflow-y-auto scrollbar-hide px-3 py-3 space-y-3 min-h-0">
		{#if messages.length === 0}
			<div class="flex flex-col items-center justify-center h-full text-center px-4">
				<div class="w-10 h-10 rounded-xl bg-teal-50 flex items-center justify-center mb-3">
					<svg class="w-5 h-5 text-teal-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
					</svg>
				</div>
				<p class="text-xs font-medium text-slate-600 mb-1">Ask me anything</p>
				<p class="text-xs text-slate-400">Market prices, unit mix, assumptions — I'll propose changes for your approval.</p>
			</div>
		{/if}

		{#each messages as msg, i}
			{#if msg.role === 'system'}
				<!-- Status pill: applied / undone / declined / warning -->
				<div class="flex justify-center items-center gap-2">
					{#if msg.content === 'applied'}
						<span class="text-[10px] px-2.5 py-0.5 rounded-full border text-emerald-600 bg-emerald-50 border-emerald-200">✓ Changes applied</span>
						{#if i === lastAppliedMsgIndex && feasibilityStore.canUndo}
							<button
								type="button"
								class="text-[10px] text-slate-400 hover:text-slate-600 underline transition-colors"
								onclick={undoChanges}
							>↩ Undo</button>
						{/if}
					{:else if msg.content === 'undone'}
						<span class="text-[10px] px-2.5 py-0.5 rounded-full border text-slate-500 bg-slate-50 border-slate-200">↩ Undone</span>
					{:else if msg.content === 'declined'}
						<span class="text-[10px] px-2.5 py-0.5 rounded-full border text-slate-400 bg-slate-50 border-slate-200">✗ Declined</span>
					{:else}
						<span class="text-[10px] px-2.5 py-0.5 rounded-full border text-amber-600 bg-amber-50 border-amber-200">⚠ {msg.content}</span>
					{/if}
				</div>
			{:else}
				<div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
					<div
						class="max-w-[88%] rounded-xl px-3 py-2 text-xs leading-relaxed
							{msg.role === 'user'
								? 'bg-teal-600 text-white'
								: 'bg-slate-100 text-slate-800'}"
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
			{/if}
		{/each}

		<!-- Pending action approval card -->
		{#if pendingActions.length > 0 && !isStreaming}
			<div class="flex justify-start">
				<div class="max-w-[92%] rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs">
					<p class="font-semibold text-amber-800 mb-2">Proposed changes</p>
					{#each pendingActions as pa}
						{@const desc = describeAction(pa)}
						<p class="text-[10px] font-semibold text-amber-600 uppercase tracking-wider mb-1">{desc.title}</p>
						<table class="w-full mb-2 text-[11px]">
							{#each desc.changes as change}
								<tr>
									{#if change.key}
										<td class="text-amber-700 pr-2 pb-0.5 whitespace-nowrap font-medium">{change.key}</td>
										<td class="text-slate-400 pr-1.5 pb-0.5 line-through tabular-nums whitespace-nowrap">{change.before}</td>
										<td class="text-amber-500 pr-1 pb-0.5">→</td>
										<td class="text-emerald-700 font-semibold pb-0.5 tabular-nums whitespace-nowrap">{change.after}</td>
									{:else}
										<td colspan="4" class="text-amber-700 pb-0.5">{change.after}</td>
									{/if}
								</tr>
							{/each}
						</table>
					{/each}
					<div class="flex gap-2 mt-1">
						<button
							type="button"
							class="flex-1 py-1 rounded-lg bg-teal-600 text-white font-medium hover:bg-teal-700 transition-colors"
							onclick={acceptChanges}
						>
							Apply
						</button>
						<button
							type="button"
							class="flex-1 py-1 rounded-lg bg-white border border-slate-200 text-slate-600 font-medium hover:bg-slate-50 transition-colors"
							onclick={declineChanges}
						>
							Decline
						</button>
					</div>
				</div>
			</div>
		{/if}

		<div bind:this={messagesEnd}></div>
	</div>

	<!-- Input -->
	<div class="flex items-end gap-2 px-3 py-3 border-t border-slate-200 flex-shrink-0">
		{#if pendingActions.length > 0}
			<p class="flex-1 text-xs text-amber-600 text-center py-1">Review the proposed changes above before continuing.</p>
		{:else}
		<textarea
			class="flex-1 px-3 py-2 text-xs rounded-xl border border-slate-200 text-slate-800 placeholder-slate-400 resize-none focus:outline-none focus:ring-2 focus:ring-teal-400 transition-all"
			placeholder="Ask anything..."
			rows="2"
			bind:value={inputValue}
			bind:this={textarea}
			onkeydown={handleKeydown}
			disabled={isStreaming}
		></textarea>
		<button
			type="button"
			aria-label="Send message"
			class="flex-shrink-0 w-8 h-8 rounded-xl bg-teal-600 text-white flex items-center justify-center hover:bg-teal-700 disabled:opacity-40 transition-colors"
			onclick={sendMessage}
			disabled={isStreaming || !inputValue.trim()}
		>
			<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
				<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
			</svg>
		</button>
		{/if}
	</div>
</div>
