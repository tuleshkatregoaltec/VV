import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { fetchPublicCollection, PublicCollectionError } from '$lib/collections/publicApi'
import * as backend from '$lib/crm/api/backend'
import { crmKeys } from '$lib/crm/queries'

const OK = {
	name: 'Marina picks',
	agent: { name: 'A' },
	items: [],
	fetched_at: '2026-11-12T00:00:00Z'
}

function stubFetch(impl: () => Promise<Response>) {
	const fn = vi.fn(impl)
	vi.stubGlobal('fetch', fn)
	return fn
}

afterEach(() => {
	vi.unstubAllGlobals()
	vi.restoreAllMocks()
})

describe('collection endpoints', () => {
	it('maps each call to its route and verb', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({})
		const post = vi.spyOn(client, 'post').mockResolvedValue({})
		const put = vi.spyOn(client, 'put').mockResolvedValue({})
		const del = vi.spyOn(client, 'delete').mockResolvedValue(undefined)
		const base = '/api/v1/crm/collections'
		await backend.listCollections({ limit: 20, offset: 40 })
		expect(get).toHaveBeenCalledWith(`${base}?limit=20&offset=40`)
		await backend.addCollectionItem('c1', { source: 'property_finder', listing_key: 'PF-1' })
		expect(put).toHaveBeenCalledWith(`${base}/c1/items`, {
			source: 'property_finder',
			listing_key: 'PF-1'
		})
		await backend.removeCollectionItem('c1', 'i1')
		expect(del).toHaveBeenCalledWith(`${base}/c1/items/i1`)
		await backend.rotateCollectionShareLink('c1')
		expect(post).toHaveBeenCalledWith(`${base}/c1/share-link/rotate`)
	})
})

describe('collection keys', () => {
	it('collection keys nest under collectionsAll', () => {
		const root = crmKeys.collectionsAll()
		for (const key of [crmKeys.collections({ limit: 10 }), crmKeys.collection('c1')]) {
			expect(key.slice(0, root.length)).toEqual([...root])
		}
		expect(crmKeys.collection('c1')).not.toEqual(crmKeys.collection('c2'))
	})
})

describe('fetchPublicCollection', () => {
	it('maps 404 to unavailable and 503 to retryable', async () => {
		stubFetch(async () => new Response('{"detail":"collection_unavailable"}', { status: 404 }))
		await expect(fetchPublicCollection('t')).rejects.toMatchObject({ kind: 'unavailable' })

		for (const status of [503, 429]) {
			stubFetch(async () => new Response('{}', { status }))
			await expect(fetchPublicCollection('t')).rejects.toMatchObject({ kind: 'retryable' })
		}
		stubFetch(async () => {
			throw new TypeError('network')
		})
		const err = await fetchPublicCollection('t').catch((e) => e)
		expect(err).toBeInstanceOf(PublicCollectionError)
		expect(err.kind).toBe('retryable')
	})

	it('sends no credentials', async () => {
		const fn = stubFetch(async () => new Response(JSON.stringify(OK), { status: 200 }))
		await expect(fetchPublicCollection('a/b')).resolves.toMatchObject({ name: 'Marina picks' })
		const [url, init] = fn.mock.calls[0] as unknown as [string, RequestInit]
		expect(url).toContain('/api/v1/public/collections/a%2Fb')
		expect(init).toMatchObject({
			cache: 'no-store',
			credentials: 'omit',
			referrerPolicy: 'no-referrer'
		})
		expect(init.headers).toBeUndefined()
	})
})
