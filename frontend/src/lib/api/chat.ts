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
}

export interface MessageListParams {
	before_id?: number
	limit?: number
}

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

	getConversations: ({ limit = 50, offset = 0 }: ConversationListParams = {}) =>
		client.get<ConversationListResponse>(
			client.withQuery('/api/v1/chat/conversations', { limit, offset })
		),

	updateConversation: (conversationId: number, title: string) =>
		client.patch<ConversationResponse, UpdateConversationRequest>(
			`/api/v1/chat/conversations/${conversationId}`,
			{ title }
		),

	deleteConversation: (conversationId: number) =>
		client.delete(`/api/v1/chat/conversations/${conversationId}`),

	getMessages: (conversationId: number, { limit = 100, before_id }: MessageListParams = {}) =>
		client.get<MessageResponse[]>(
			client.withQuery(`/api/v1/chat/conversations/${conversationId}/messages`, {
				limit,
				before_id
			})
		),

	/** Streams AI response chunks via Server-Sent Events */
	sendMessage: (conversationId: number, message: string, onChunk: StreamCallback) =>
		client.stream(`/api/v1/chat/conversations/${conversationId}/messages/stream`, onChunk, {
			method: 'POST',
			body: { message }
		})
}
