import { env } from '$env/dynamic/public'
import type { PublicCollectionResponse } from '$lib/api/generated/hey-api/types.gen'

/**
 * Public collection fetch. Deliberately separate from the CRM client: no auth header, no
 * cookies, no interceptors, and no referrer, because the share token is a bearer credential.
 *
 * `unavailable`: the link is invalid, switched off or the account is suspended (404).
 * `retryable`: the data could not be loaded right now (503, 429 or network).
 */
export class PublicCollectionError extends Error {
	constructor(
		public kind: 'unavailable' | 'retryable',
		public status?: number
	) {
		super(kind === 'unavailable' ? 'collection_unavailable' : 'collection_retryable')
		this.name = 'PublicCollectionError'
	}
}

export async function fetchPublicCollection(token: string): Promise<PublicCollectionResponse> {
	let res: Response
	try {
		res = await fetch(
			`${env.PUBLIC_API_BASE_URL}/api/v1/public/collections/${encodeURIComponent(token)}`,
			{ cache: 'no-store', credentials: 'omit', referrerPolicy: 'no-referrer' }
		)
	} catch {
		throw new PublicCollectionError('retryable')
	}
	if (res.ok) return (await res.json()) as PublicCollectionResponse
	throw new PublicCollectionError(res.status === 404 ? 'unavailable' : 'retryable', res.status)
}
