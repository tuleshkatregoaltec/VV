import { createQuery } from '@tanstack/svelte-query'
import { browser } from '$app/environment'
import { chatQueries, chatScope } from '$lib/queries/chat'

const selection = $state<{ scope: string | null; id: number | null }>({ scope: null, id: null })

/** Only IDs in the current authenticated conversation list can become active. */
export function createConversationSelection(initialId: number | null = null) {
	const conversations = createQuery(() => ({
		...chatQueries.conversations(),
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
					saved = Number(sessionStorage.getItem(`chat:conversation:${scope}`)) || null
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
					if (id === null) sessionStorage.removeItem(`chat:conversation:${scope}`)
					else sessionStorage.setItem(`chat:conversation:${scope}`, String(id))
				} catch {
					/* Selection still persists for this app session. */
				}
			}
		}
	}
}
