import { createQuery } from '@tanstack/svelte-query'
import { browser } from '$app/environment'
import { CHAT_SELECTION_SESSION_PREFIX } from '$lib/auth/user-browser-state'
import type { ChatAssistant } from '$lib/api/chat'
import { chatQueries, chatScope } from '$lib/queries/chat'

// One remembered selection per assistant: each page has its own history.
const selections: Record<ChatAssistant, { scope: string | null; id: number | null }> = $state({
	crm: { scope: null, id: null },
	market: { scope: null, id: null }
})

/** The session key for an assistant's selection (the CRM key is unchanged from before). */
function storageKey(assistant: ChatAssistant, scope: string): string {
	return `${CHAT_SELECTION_SESSION_PREFIX}${assistant === 'crm' ? '' : `${assistant}:`}${scope}`
}

/** Only IDs in the current authenticated conversation list of this assistant can become active. */
export function createConversationSelection(
	initialId: number | null = null,
	assistant: ChatAssistant = 'crm'
) {
	const selection = selections[assistant]
	const conversations = createQuery(() => ({
		...chatQueries.conversations(assistant),
		refetchOnMount: 'always'
	}))
	let initialPending = initialId
	return {
		get id(): number | null {
			const scope = chatScope()
			if (
				!scope ||
				!conversations.isSuccess ||
				(initialPending !== null && !conversations.isFetchedAfterMount)
			)
				return null
			let saved = selection.scope === scope ? selection.id : null
			if (browser && selection.scope !== scope) {
				try {
					saved = Number(sessionStorage.getItem(storageKey(assistant, scope))) || null
				} catch {
					/* Storage can be unavailable in private browsing. */
				}
			}
			const candidate = initialPending ?? saved
			const available = conversations.data?.conversations ?? []
			return available.find((item) => item.id === candidate)?.id ?? available[0]?.id ?? null
		},
		set id(id: number | null) {
			const scope = chatScope()
			if (!scope || (initialPending !== null && !conversations.isFetchedAfterMount)) return
			initialPending = null
			selection.scope = scope
			selection.id = id
			if (browser) {
				try {
					if (id === null) sessionStorage.removeItem(storageKey(assistant, scope))
					else sessionStorage.setItem(storageKey(assistant, scope), String(id))
				} catch {
					/* Selection still persists for this app session. */
				}
			}
		}
	}
}
