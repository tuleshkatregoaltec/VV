<script lang="ts">
import { feasibility } from '$lib/api/feasibility'
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { titleCase } from '$lib/feasibility/workbook/utils'
import { feasibilityStudy } from '$lib/stores/feasibilityStudy.svelte'
import { feasibilityWorkspace } from '$lib/stores/feasibilityWorkspace.svelte'

let draft = $state('')

function mergeHistoryJson(current: string | null, next: string | null | undefined) {
	if (!next) return current
	if (!current) return next
	try {
		const currentMessages = JSON.parse(current)
		const nextMessages = JSON.parse(next)
		if (Array.isArray(currentMessages) && Array.isArray(nextMessages)) {
			return JSON.stringify([...currentMessages, ...nextMessages])
		}
	} catch {
		return next
	}
	return next
}

async function sendMessage() {
	if (!draft.trim() || !workbookStore.plotData || feasibilityWorkspace.streaming) return
	const content = draft.trim()
	draft = ''
	feasibilityWorkspace.pushMessage({ role: 'user', content })
	const assistantIndex = feasibilityWorkspace.startAssistantMessage()
	feasibilityWorkspace.setStreaming(true)

	await feasibility.streamChat(
		[{ role: 'user', content }],
		{
			plot_data: workbookStore.plotData!,
			assumptions: workbookStore.inputs,
			research: workbookStore.research!,
			history_json: feasibilityWorkspace.historyJson
		},
		(chunk) => {
			try {
				const parsed = JSON.parse(chunk)
				if (parsed.type === 'text') {
					feasibilityWorkspace.appendAssistantChunk(assistantIndex, parsed.content)
				} else if (parsed.type === 'pending_action') {
					feasibilityWorkspace.setPendingProposal({
						action: parsed.action,
						payload: parsed.payload
					})
				} else if (parsed.type === 'show_research') {
					feasibilityWorkspace.setResearchEvent({
						tab: parsed.tab,
						data: parsed.data
					})
				} else if (parsed.type === 'done') {
					feasibilityWorkspace.setHistoryJson(
						mergeHistoryJson(feasibilityWorkspace.historyJson, parsed.new_messages_json)
					)
					feasibilityWorkspace.setStreaming(false)
					void feasibilityStudy.persistChatState(feasibilityWorkspace.chatState)
				} else if (parsed.type === 'error') {
					feasibilityWorkspace.appendAssistantChunk(assistantIndex, `\n${parsed.error}`)
					feasibilityWorkspace.setStreaming(false)
				}
			} catch {
				feasibilityWorkspace.appendAssistantChunk(assistantIndex, chunk)
			}
		}
	)
}

function acceptProposal() {
	const proposal = feasibilityWorkspace.pendingProposal
	if (!proposal) return
	const applied = workbookStore.applyProposal(proposal)
	feasibilityWorkspace.pushMessage({
		role: 'system',
		content: applied ? `Applied ${proposal.action}` : `Could not apply ${proposal.action}`
	})
	feasibilityWorkspace.setPendingProposal(null)
	if (applied) {
		feasibilityStudy.markUnsaved()
		void feasibilityStudy.saveCurrentWorkbook(workbookStore.assumptions, {
			chatState: feasibilityWorkspace.chatState
		})
		return
	}
	void feasibilityStudy.persistChatState(feasibilityWorkspace.chatState)
}

function dismissProposal() {
	feasibilityWorkspace.setPendingProposal(null)
	void feasibilityStudy.persistChatState(feasibilityWorkspace.chatState)
}
</script>

<div class="ui-surface flex h-full flex-col">
	<div class="border-b border-border px-4 py-4">
		<p class="text-sm font-semibold text-fg-1">Chat</p>
		<p class="mt-1 text-xs text-fg-4">Structured proposals apply to the current study state.</p>
	</div>

	<div class="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4">
		{#if feasibilityWorkspace.chatMessages.length === 0}
			<p class="text-sm text-fg-4">Ask for explanation or propose a model change such as reducing pricing by 5%.</p>
		{/if}
		{#each feasibilityWorkspace.chatMessages as message}
			<div class="rounded-lg px-3 py-2 text-sm {message.role === 'user' ? 'bg-navy text-bone' : message.role === 'assistant' ? 'bg-panel text-fg-2' : 'bg-info-bg text-info'}">
				<p class="text-[11px] font-semibold uppercase tracking-[0.14em] opacity-70">{message.role}</p>
				<p class="mt-1 whitespace-pre-wrap">{message.content || (feasibilityWorkspace.streaming && message.role === 'assistant' ? '…' : '')}</p>
			</div>
		{/each}

		{#if feasibilityWorkspace.pendingProposal}
			<div class="rounded-lg border border-[rgba(165,90,19,0.24)] bg-warning-bg p-4 text-sm text-warning">
				<p class="font-semibold">Pending proposal</p>
				<p class="mt-2">{titleCase(feasibilityWorkspace.pendingProposal.action)}</p>
				<pre class="mt-3 overflow-auto rounded-md bg-card/70 p-3 text-xs">{JSON.stringify(feasibilityWorkspace.pendingProposal.payload, null, 2)}</pre>
				<div class="mt-3 flex gap-2">
					<button type="button" class="rounded-md bg-warning px-3 py-2 text-xs font-medium text-white" onclick={acceptProposal}>Apply</button>
					<button type="button" class="rounded-md border border-[rgba(165,90,19,0.24)] px-3 py-2 text-xs font-medium text-warning" onclick={dismissProposal}>Dismiss</button>
				</div>
			</div>
		{/if}
	</div>

	<div class="border-t border-border p-4">
		<textarea
			bind:value={draft}
			rows="4"
			class="ui-field w-full px-3 py-2 text-sm"
			placeholder="Explain the current returns, or propose a structured change."
		></textarea>
		<button
			type="button"
			data-variant="primary"
			class="ui-button mt-3 w-full px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-60"
			onclick={() => void sendMessage()}
			disabled={feasibilityWorkspace.streaming}
		>
			{feasibilityWorkspace.streaming ? 'Streaming…' : 'Send'}
		</button>
	</div>
</div>
