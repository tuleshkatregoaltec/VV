/** CRM Assistant API (/api/v1/crm/assistant): its own conversations, separate from market chat. */
import type { StreamCallback } from '$lib/api/client'
import { client } from '$lib/api/client'
import type {
	AssistantActionResult,
	AssistantConversationListResponse,
	AssistantConversationResponse,
	AssistantMessageResponse
} from '$lib/api/generated/hey-api/types.gen'

export type { AssistantActionResult, AssistantConversationResponse, AssistantMessageResponse }

const BASE = '/api/v1/crm/assistant'

export const assistant = {
	listConversations: (limit = 50) =>
		client.get<AssistantConversationListResponse>(
			client.withQuery(`${BASE}/conversations`, { limit, offset: 0 })
		),

	createConversation: (title?: string) =>
		client.post<AssistantConversationResponse>(`${BASE}/conversations`, { title }),

	renameConversation: (id: number, title: string) =>
		client.patch<AssistantConversationResponse>(`${BASE}/conversations/${id}`, { title }),

	deleteConversation: (id: number) => client.delete(`${BASE}/conversations/${id}`),

	getMessages: (id: number) =>
		client.get<AssistantMessageResponse[]>(
			client.withQuery(`${BASE}/conversations/${id}/messages`, { limit: 200 })
		),

	/** Streams the reply as SSE data lines (see ./stream for the events). */
	sendMessage: (id: number, message: string, onChunk: StreamCallback) =>
		client.stream(`${BASE}/conversations/${id}/messages/stream`, onChunk, {
			method: 'POST',
			body: { message }
		}),

	/** `edits` sends the agent's edited email instead of the proposed one. */
	confirmAction: (actionId: string, edits?: { subject: string; body: string }) =>
		client.post<AssistantActionResult>(
			`${BASE}/actions/${actionId}/confirm`,
			edits ? { edits } : {}
		),

	cancelAction: (actionId: string) =>
		client.post<AssistantActionResult>(`${BASE}/actions/${actionId}/cancel`, {})
}

export const assistantKeys = {
	all: ['crm', 'assistant'] as const,
	conversations: () => [...assistantKeys.all, 'conversations'] as const,
	messages: (id: number) => [...assistantKeys.all, 'messages', id] as const
}
