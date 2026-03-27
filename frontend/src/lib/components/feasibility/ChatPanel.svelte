<script lang="ts">
import { feasibility } from '$lib/api/feasibility'
import { workbookStore } from '$lib/feasibility/workbook/store.svelte'
import { titleCase } from '$lib/feasibility/workbook/utils'
import { feasibilityWorkspace } from '$lib/stores/feasibilityWorkspace.svelte'

let draft = $state('')

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
			research: workbookStore.research!
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
					feasibilityWorkspace.setStreaming(false)
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
}
</script>

<div class="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
	<div class="border-b border-slate-200 px-4 py-4">
		<p class="text-sm font-semibold text-slate-900">Chat</p>
		<p class="mt-1 text-xs text-slate-500">Structured proposals apply to the current study state.</p>
	</div>

	<div class="min-h-0 flex-1 space-y-3 overflow-auto px-4 py-4">
		{#if feasibilityWorkspace.chatMessages.length === 0}
			<p class="text-sm text-slate-500">Ask for explanation or propose a model change such as reducing pricing by 5%.</p>
		{/if}
		{#each feasibilityWorkspace.chatMessages as message}
			<div class="rounded-2xl px-3 py-2 text-sm {message.role === 'user' ? 'bg-slate-900 text-white' : message.role === 'assistant' ? 'bg-slate-100 text-slate-700' : 'bg-teal-50 text-teal-700'}">
				<p class="text-[11px] font-semibold uppercase tracking-[0.14em] opacity-70">{message.role}</p>
				<p class="mt-1 whitespace-pre-wrap">{message.content || (feasibilityWorkspace.streaming && message.role === 'assistant' ? '…' : '')}</p>
			</div>
		{/each}

		{#if feasibilityWorkspace.pendingProposal}
			<div class="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
				<p class="font-semibold">Pending proposal</p>
				<p class="mt-2">{titleCase(feasibilityWorkspace.pendingProposal.action)}</p>
				<pre class="mt-3 overflow-auto rounded-xl bg-white/70 p-3 text-xs">{JSON.stringify(feasibilityWorkspace.pendingProposal.payload, null, 2)}</pre>
				<div class="mt-3 flex gap-2">
					<button type="button" class="rounded-xl bg-amber-600 px-3 py-2 text-xs font-medium text-white" onclick={acceptProposal}>Apply</button>
					<button type="button" class="rounded-xl border border-amber-300 px-3 py-2 text-xs font-medium text-amber-700" onclick={() => feasibilityWorkspace.setPendingProposal(null)}>Dismiss</button>
				</div>
			</div>
		{/if}
	</div>

	<div class="border-t border-slate-200 p-4">
		<textarea
			bind:value={draft}
			rows="4"
			class="w-full rounded-2xl border border-slate-300 px-3 py-2 text-sm outline-none transition focus:border-teal-500"
			placeholder="Explain the current returns, or propose a structured change."
		></textarea>
		<button
			type="button"
			class="mt-3 w-full rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-teal-700 disabled:cursor-not-allowed disabled:opacity-60"
			onclick={() => void sendMessage()}
			disabled={feasibilityWorkspace.streaming}
		>
			{feasibilityWorkspace.streaming ? 'Streaming…' : 'Send'}
		</button>
	</div>
</div>
