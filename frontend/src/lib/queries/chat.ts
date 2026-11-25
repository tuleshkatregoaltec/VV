import { type ChatAssistant, chat } from '$lib/api/chat'
import { currentUser } from '$lib/stores/user.svelte'

export function chatScope(): string | null {
	const user = currentUser.data
	return user ? `${user.id}:${user.organization_id ?? ''}` : null
}

export const chatKeys = {
	all: ['chat'] as const,
	action: (actionId: string) => [...chatKeys.all, chatScope(), 'action', actionId] as const,
	// Each assistant has its own history list.
	conversations: (assistant: ChatAssistant = 'crm', limit = 50, offset = 0) =>
		[...chatKeys.all, chatScope(), 'conversations', assistant, { limit, offset }] as const,
	messages: (conversationId: number, limit = 100, assistant: ChatAssistant = 'crm') =>
		[...chatKeys.all, chatScope(), 'messages', assistant, { conversationId, limit }] as const
}

export const chatQueries = {
	action: (actionId: string) => ({
		queryKey: chatKeys.action(actionId),
		queryFn: () => chat.getAction(actionId),
		enabled: chatScope() !== null,
		staleTime: 0
	}),
	conversations: (assistant: ChatAssistant = 'crm', limit = 50, offset = 0) => ({
		queryKey: chatKeys.conversations(assistant, limit, offset),
		queryFn: () => chat.getConversations({ limit, offset, assistant }),
		enabled: chatScope() !== null,
		staleTime: 60 * 1000
	}),
	// A conversation belongs to one assistant, so its ID alone keys its messages; the request
	// still names the assistant, and the server finds no other assistant's conversation.
	messages: (conversationId: number | null, limit = 100, assistant: ChatAssistant = 'crm') => ({
		queryKey: chatKeys.messages(conversationId ?? 0, limit, assistant),
		queryFn: () => chat.getMessages(conversationId ?? 0, { limit, assistant }),
		enabled: conversationId !== null && chatScope() !== null,
		staleTime: 5 * 60 * 1000
	})
}
