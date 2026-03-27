import { feasibility } from '$lib/api/feasibility'
import type { FeasibilityAssumptions, PlotResearch } from '$lib/api/generated/hey-api/types.gen'
import type { FeasibilityChatMessage, PlotDetails } from '$lib/feasibility/workbook/models'

export interface PendingProposal {
	action: string
	payload: unknown
}

interface ChatContext {
	plotData: PlotDetails
	assumptions: FeasibilityAssumptions
	research: PlotResearch
}

const chatMessages = $state<{ value: FeasibilityChatMessage[] }>({ value: [] })
const pendingProposal = $state({ value: null as PendingProposal | null })
const streaming = $state({ value: false })
const loadingStepIndex = $state({ value: 0 })
const latestResearchEvent = $state<{ value: { tab: string; data: unknown } | null }>({
	value: null
})

function setStreaming(next: boolean) {
	streaming.value = next
}

function pushMessage(message: FeasibilityChatMessage) {
	chatMessages.value = [...chatMessages.value, message]
}

function startAssistantMessage() {
	chatMessages.value = [...chatMessages.value, { role: 'assistant', content: '' }]
	return chatMessages.value.length - 1
}

function appendAssistantChunk(index: number, chunk: string) {
	chatMessages.value = chatMessages.value.map((message, currentIndex) =>
		currentIndex === index ? { ...message, content: `${message.content}${chunk}` } : message
	)
}

function setPendingProposal(proposal: PendingProposal | null) {
	pendingProposal.value = proposal
}

function setResearchEvent(event: { tab: string; data: unknown } | null) {
	latestResearchEvent.value = event
}

async function sendMessage(content: string, context: ChatContext) {
	const trimmed = content.trim()
	if (!trimmed || streaming.value) return
	pushMessage({ role: 'user', content: trimmed })
	const assistantIndex = startAssistantMessage()
	setStreaming(true)

	await feasibility.streamChat(
		[{ role: 'user', content: trimmed }],
		{
			plot_data: context.plotData,
			assumptions: context.assumptions,
			research: context.research
		},
		(chunk) => {
			try {
				const parsed = JSON.parse(chunk)
				if (parsed.type === 'text') {
					appendAssistantChunk(assistantIndex, parsed.content)
				} else if (parsed.type === 'pending_action') {
					setPendingProposal({
						action: parsed.action,
						payload: parsed.payload
					})
				} else if (parsed.type === 'show_research') {
					setResearchEvent({
						tab: parsed.tab,
						data: parsed.data
					})
				} else if (parsed.type === 'done') {
					setStreaming(false)
				} else if (parsed.type === 'error') {
					appendAssistantChunk(assistantIndex, `\n${parsed.error}`)
					setStreaming(false)
				}
			} catch {
				appendAssistantChunk(assistantIndex, chunk)
			}
		}
	)
}

export const loadingSteps = [
	'Reading plot data',
	'Researching market evidence',
	'Setting project assumptions',
	'Building financial model',
	'Finalizing study'
]

export const feasibilityWorkspace = {
	get chatMessages() {
		return chatMessages.value
	},
	get pendingProposal() {
		return pendingProposal.value
	},
	get streaming() {
		return streaming.value
	},
	get loadingStepIndex() {
		return loadingStepIndex.value
	},
	get latestResearchEvent() {
		return latestResearchEvent.value
	},
	setStreaming,
	advanceLoadingStep() {
		loadingStepIndex.value = (loadingStepIndex.value + 1) % loadingSteps.length
	},
	resetLoading() {
		loadingStepIndex.value = 0
	},
	pushMessage,
	startAssistantMessage,
	appendAssistantChunk,
	setPendingProposal,
	setResearchEvent,
	sendMessage,
	reset() {
		chatMessages.value = []
		pendingProposal.value = null
		streaming.value = false
		loadingStepIndex.value = 0
		latestResearchEvent.value = null
	}
}
