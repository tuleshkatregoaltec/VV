import { whatsapp } from '$lib/api/whatsapp'
import { currentUser } from '$lib/stores/user.svelte'

export function whatsappScope(): string | null {
	const user = currentUser.data
	return user ? `${user.id}:${user.organization_id ?? ''}` : null
}

export const whatsappKeys = {
	all: ['whatsapp'] as const,
	connections: () => [...whatsappKeys.all, whatsappScope(), 'connections'] as const,
	listings: (connectionId: string) =>
		[...whatsappKeys.all, whatsappScope(), 'listings', connectionId] as const,
	notifications: () => [...whatsappKeys.all, whatsappScope(), 'notifications'] as const,
	threads: (connectionId: string) =>
		[...whatsappKeys.all, whatsappScope(), 'threads', connectionId] as const,
	messages: (threadId: string) =>
		[...whatsappKeys.all, whatsappScope(), 'messages', threadId] as const
}

export const whatsappQueries = {
	listings: (connectionId: string | null) => ({
		queryKey: whatsappKeys.listings(connectionId ?? ''),
		queryFn: () => whatsapp.listings(connectionId ?? ''),
		enabled: connectionId !== null && whatsappScope() !== null,
		staleTime: 0,
		refetchInterval: 5000
	}),
	connections: () => ({
		queryKey: whatsappKeys.connections(),
		queryFn: () => whatsapp.connections(),
		enabled: whatsappScope() !== null,
		staleTime: 0,
		refetchInterval: 5000
	}),
	notifications: () => ({
		queryKey: whatsappKeys.notifications(),
		queryFn: () => whatsapp.notifications(),
		enabled: whatsappScope() !== null,
		staleTime: 0,
		refetchInterval: 2000,
		refetchIntervalInBackground: true
	}),
	threads: (connectionId: string | null) => ({
		queryKey: whatsappKeys.threads(connectionId ?? ''),
		queryFn: () => whatsapp.threads(connectionId ?? ''),
		enabled: connectionId !== null && whatsappScope() !== null,
		staleTime: 0,
		refetchInterval: 5000
	}),
	messages: (threadId: string | null) => ({
		queryKey: whatsappKeys.messages(threadId ?? ''),
		queryFn: () => whatsapp.messages(threadId ?? ''),
		enabled: threadId !== null && whatsappScope() !== null,
		staleTime: 0,
		refetchInterval: 2000
	})
}
