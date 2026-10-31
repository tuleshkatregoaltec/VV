import { chat } from '$lib/api/chat'
import { currentUser } from '$lib/stores/user.svelte'

export function chatScope(): string | null {
	const user = currentUser.data
	return user ? `${user.id}:${user.organization_id ?? ''}` : null
}

export const chatKeys = {
	all: ['chat'] as const,
	action: (actionId: string) => [...chatKeys.all, chatScope(), 'action', actionId] as const,
	conversations: (limit = 50, offset = 0) =>
		[...chatKeys.all, chatScope(), 'conversations', { limit, offset }] as const,
	messages: (conversationId: number, limit = 100) =>
		[...chatKeys.all, chatScope(), 'messages', { conversationId, limit }] as const
}

export const chatQueries = {
	action: (actionId: string) => ({
		queryKey: chatKeys.action(actionId),
		queryFn: () => chat.getAction(actionId),
		enabled: chatScope() !== null,
		staleTime: 0
	}),
	conversations: (limit = 50, offset = 0) => ({
		queryKey: chatKeys.conversations(limit, offset),
		queryFn: () => chat.getConversations({ limit, offset }),
		enabled: chatScope() !== null,
		staleTime: 60 * 1000
	}),
	messages: (conversationId: number | null, limit = 100) => ({
		queryKey: chatKeys.messages(conversationId ?? 0, limit),
		queryFn: () => chat.getMessages(conversationId ?? 0, { limit }),
		enabled: conversationId !== null && chatScope() !== null,
		staleTime: 5 * 60 * 1000
	})
}
