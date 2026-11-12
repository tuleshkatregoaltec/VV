/** Collection writes: one call, a one-line toast on failure, and the collection views refreshed on settle. */
import { ApiError } from '$lib/api/client'
import { crm } from '$lib/crm/api'
import { crmKeys, invalidateCollection } from '$lib/crm/queries'
import { toast } from '$lib/crm/stores/toast.svelte'
import { errorText } from '$lib/crm/write'
import { getQueryClient } from '$lib/queries/client'

const CODE_TEXT: Record<string, string> = {
	collection_full: 'This collection is full (50 / 50).',
	sharing_disabled: 'Turn sharing on first.',
	collection_not_found: 'That collection isn’t there any more.'
}

function failure(e: unknown): string {
	if (e instanceof ApiError && e.code && CODE_TEXT[e.code]) return CODE_TEXT[e.code]
	return errorText(e)
}

/** Run a collection write; null when it failed (already shown). */
async function run<T>(
	id: string | null,
	call: () => Promise<T>,
	success?: string
): Promise<T | null> {
	const qc = getQueryClient()
	try {
		const r = await call()
		if (success) toast.show(success)
		return r
	} catch (e) {
		toast.show(failure(e), { tone: 'error' })
		return null
	} finally {
		if (id) await invalidateCollection(qc, id)
		else await qc.invalidateQueries({ queryKey: crmKeys.collectionsAll() })
	}
}

export const createCollection = (name: string) => run(null, () => crm.collections.create({ name }))

export const renameCollection = (id: string, name: string) =>
	run(id, () => crm.collections.update(id, { name }))

export const setSharing = (id: string, enabled: boolean) =>
	run(id, () => crm.collections.update(id, { sharing_enabled: enabled }))

/** After a delete the detail is gone: leave it first, drop it from the cache (never refetch it), refresh the list. */
export async function deleteCollection(id: string, onDeleted: () => void) {
	const qc = getQueryClient()
	try {
		await crm.collections.remove(id)
	} catch (e) {
		toast.show(failure(e), { tone: 'error' })
		return false
	}
	onDeleted()
	qc.removeQueries({ queryKey: crmKeys.collection(id) })
	await qc.invalidateQueries({ queryKey: crmKeys.collectionsAll() })
	toast.show('Collection deleted')
	return true
}

export const removeItem = (id: string, itemId: string) =>
	run(id, () => crm.collections.removeItem(id, itemId))

export const addListing = (id: string, listingKey: string) =>
	run(
		id,
		() => crm.collections.addItem(id, { source: 'property_finder', listing_key: listingKey }),
		'Added to collection'
	)

export async function copyShareLink(
	id: string,
	writeText: (text: string) => Promise<void> = (t) => navigator.clipboard.writeText(t)
) {
	return run(
		id,
		async () => {
			const { url } = await crm.collections.shareLink(id)
			await writeText(url)
		},
		'Link copied'
	)
}

export async function rotateShareLink(id: string) {
	return run(
		id,
		() => crm.collections.rotateLink(id),
		'New link created. The old link no longer works.'
	)
}
