import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import { currentUser } from '$lib/stores/user.svelte'
import { contactsSyncPending } from '$lib/whatsapp/connect-state'

const scope = () => {
	const user = currentUser.data
	return user ? `${user.id}:${user.organization_id ?? ''}` : null
}

export const CONTACTS_PAGE_SIZE = 100
export const SYNC_POLL_MS = 5000

export const whatsappConnectKeys = {
	all: ['whatsapp-connect'] as const,
	config: () => [...whatsappConnectKeys.all, scope(), 'config'] as const,
	status: () => [...whatsappConnectKeys.all, scope(), 'status'] as const,
	contacts: (search: string, blockedOnly: boolean) =>
		[...whatsappConnectKeys.all, scope(), 'contacts', search, blockedOnly] as const,
	admin: () => [...whatsappConnectKeys.all, scope(), 'admin'] as const
}

export const whatsappConnectQueries = {
	config: () => ({
		queryKey: whatsappConnectKeys.config(),
		queryFn: () => whatsappConnect.signupConfig(),
		enabled: scope() !== null,
		staleTime: 0,
		// The signed state token lasts 30 minutes; keep a fresh one for a page left open.
		refetchInterval: 15 * 60 * 1000
	}),
	status: () => ({
		queryKey: whatsappConnectKeys.status(),
		queryFn: () => whatsappConnect.status(),
		enabled: scope() !== null,
		staleTime: 0,
		// Contacts arrive by webhook a few minutes after connecting; watch until they do.
		refetchInterval: (query: { state: { data: AgentConnectionStatus | null | undefined } }) => {
			const status = query.state.data
			return status?.state === 'connected' && contactsSyncPending(status) ? SYNC_POLL_MS : false
		}
	}),
	contacts: (search: string, blockedOnly: boolean, enabled: boolean, pollMs: number | false) => ({
		queryKey: whatsappConnectKeys.contacts(search, blockedOnly),
		queryFn: ({ pageParam }: { pageParam: number }) =>
			whatsappConnect.contacts({
				search,
				blocked: blockedOnly ? true : undefined,
				limit: CONTACTS_PAGE_SIZE,
				offset: pageParam
			}),
		initialPageParam: 0,
		getNextPageParam: (last: { offset: number; limit: number; total: number }) =>
			last.offset + last.limit < last.total ? last.offset + last.limit : undefined,
		enabled: enabled && scope() !== null,
		staleTime: 0,
		refetchInterval: pollMs
	}),
	admin: () => ({
		queryKey: whatsappConnectKeys.admin(),
		queryFn: () => whatsappConnect.adminConnections(),
		staleTime: 0
	})
}
