import type { StreamCallback } from './client'
import { client } from './client'
import type {
	ConversationListResponse,
	ConversationResponse,
	CreateConversationRequest,
	MessageResponse,
	UpdateConversationRequest
} from './generated/hey-api/types.gen'

export type { ConversationResponse, CreateConversationRequest, MessageResponse }

export const chat = {
	createConversation: (data: CreateConversationRequest = {}) =>
		client.post<ConversationResponse>('/api/v1/chat/conversations', data),

	getConversations: () => client.get<ConversationListResponse>('/api/v1/chat/conversations'),

	updateConversation: (conversationId: number, title: string) =>
		client.patch<ConversationResponse, UpdateConversationRequest>(
			`/api/v1/chat/conversations/${conversationId}`,
			{ title }
		),

	deleteConversation: (conversationId: number) =>
		client.delete(`/api/v1/chat/conversations/${conversationId}`),

	getMessages: (conversationId: number) =>
		client.get<MessageResponse[]>(`/api/v1/chat/conversations/${conversationId}/messages`),

	/** Streams AI response chunks via Server-Sent Events */
	sendMessage: (conversationId: number, message: string, onChunk: StreamCallback) =>
		client.stream(`/api/v1/chat/conversations/${conversationId}/messages/stream`, onChunk, {
			method: 'POST',
			body: { message }
		})
}
