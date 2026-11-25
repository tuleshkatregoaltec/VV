import type { StreamCallback } from './client'
import { client } from './client'
import type {
	ActionProposalRequest,
	ActionProposalResponse,
	ConversationListResponse,
	ConversationResponse,
	CreateConversationRequest,
	MessageResponse,
	UpdateConversationRequest
} from './generated/hey-api/types.gen'

export type {
	ActionProposalResponse,
	ConversationListResponse,
	ConversationResponse,
	CreateConversationRequest,
	MessageResponse
}

export interface ConversationListParams {
	limit?: number
	offset?: number
	/** Whose history: the CRM Operations Assistant (default) or Market AI. */
	assistant?: ChatAssistant
}

export interface MessageListParams {
	before_id?: number
	limit?: number
	/** Only a conversation of this assistant (the other assistant's is not found). */
	assistant?: ChatAssistant
}

/** Which chat product answers: the CRM Operations Assistant or Market AI. */
export type ChatAssistant = 'crm' | 'market'

export const chat = {
	getAction: (actionId: string) =>
		client.get<ActionProposalResponse>(`/api/v1/assistant/actions/${encodeURIComponent(actionId)}`),
	getActions: (conversationId: number) =>
		client.get<ActionProposalResponse[]>(
			client.withQuery('/api/v1/assistant/actions/proposals', { conversation_id: conversationId })
		),
	proposeAction: (data: ActionProposalRequest) =>
		client.post<ActionProposalResponse, ActionProposalRequest>(
			'/api/v1/assistant/actions/proposals',
			data
		),
	confirmAction: (actionId: string) =>
		client.post<ActionProposalResponse>(
			`/api/v1/assistant/actions/${encodeURIComponent(actionId)}/confirm`
		),
	cancelAction: (actionId: string) =>
		client.post<ActionProposalResponse>(
			`/api/v1/assistant/actions/${encodeURIComponent(actionId)}/cancel`
		),

	/** The words in a voice recording (16 kHz mono WAV), for the agent to check before sending. */
	transcribe: (audio: Blob) => {
		const form = new FormData()
		form.append('audio', audio, 'voice.wav')
		return client.post<{ text: string }>('/api/v1/chat/transcribe', form)
	},

	createConversation: (data: CreateConversationRequest = {}) =>
		client.post<ConversationResponse>('/api/v1/chat/conversations', data),

	getConversations: ({ limit = 50, offset = 0, assistant = 'crm' }: ConversationListParams = {}) =>
		client.get<ConversationListResponse>(
			client.withQuery('/api/v1/chat/conversations', { limit, offset, assistant })
		),

	updateConversation: (conversationId: number, title: string, assistant: ChatAssistant = 'crm') =>
		client.patch<ConversationResponse, UpdateConversationRequest>(
			client.withQuery(`/api/v1/chat/conversations/${conversationId}`, { assistant }),
			{ title }
		),

	deleteConversation: (conversationId: number, assistant: ChatAssistant = 'crm') =>
		client.delete(client.withQuery(`/api/v1/chat/conversations/${conversationId}`, { assistant })),

	getMessages: (
		conversationId: number,
		{ limit = 100, before_id, assistant }: MessageListParams = {}
	) =>
		client.get<MessageResponse[]>(
			client.withQuery(`/api/v1/chat/conversations/${conversationId}/messages`, {
				limit,
				before_id,
				assistant
			})
		),

	/**
	 * Streams AI response chunks via Server-Sent Events. Each product answers from its own
	 * endpoint over the shared conversation list: the CRM Operations Assistant (default) or
	 * Market AI (/chat).
	 */
	sendMessage: (
		conversationId: number,
		message: string,
		onChunk: StreamCallback,
		assistant: ChatAssistant = 'crm'
	) =>
		client.stream(
			`/api/v1/${assistant === 'market' ? 'market-chat' : 'chat'}/conversations/${conversationId}/messages/stream`,
			onChunk,
			{ method: 'POST', body: { message } }
		)
}
