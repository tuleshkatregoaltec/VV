import { render } from 'svelte/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { PublicCollectionResponse } from '$lib/api/generated/hey-api/types.gen'

// The repo has no DOM test environment, so the page is server-rendered with the query result
// mocked; state selection and copy are what is under test.
const q = vi.hoisted(() => ({
	state: {} as Record<string, unknown>,
	options: undefined as unknown
}))

vi.mock('@tanstack/svelte-query', () => ({
	createQuery: (fn: () => unknown) => {
		q.options = fn()
		return q.state
	}
}))
vi.mock('$app/state', () => ({ page: { params: { token: 'secret-token' } } }))
vi.mock('$lib/collections/publicApi', async () => {
	class PublicCollectionError extends Error {
		constructor(
			public kind: 'unavailable' | 'retryable',
			public status?: number
		) {
			super(kind)
		}
	}
	return { PublicCollectionError, fetchPublicCollection: vi.fn() }
})

import { PublicCollectionError } from '$lib/collections/publicApi'
import Page from '../../src/routes/collections/[token]/+page.svelte'

const data: PublicCollectionResponse = {
	name: 'Marina picks',
	agent: { name: 'Sara Ali', email: 'sara@example.com', phone: '+971501234567' },
	fetched_at: '2026-11-12T12:00:00Z',
	items: [
		{
			status: 'available',
			title: 'Sea view 2BR',
			price_aed: 2500000,
			mode: 'sale',
			updated_at: '2026-11-12T10:00:00Z'
		},
		{ status: 'unavailable' }
	]
}

const html = () => render(Page).body

describe('public collection page', () => {
	beforeEach(() => {
		q.state = { isPending: false, isError: false, data: undefined, error: null, refetch: vi.fn() }
	})

	it('uses a never-cached query keyed by token', () => {
		html()
		expect(q.options).toMatchObject({
			queryKey: ['public-collection', 'secret-token'],
			staleTime: 0,
			gcTime: 0,
			refetchOnWindowFocus: true,
			refetchOnMount: 'always'
		})
	})

	it('renders loading', () => {
		q.state = { ...q.state, isPending: true }
		expect(html()).toContain('Loading')
	})

	it('renders unavailable', () => {
		q.state = { ...q.state, isError: true, error: new PublicCollectionError('unavailable', 404) }
		const out = html()
		expect(out).toContain('This collection is no longer available.')
		expect(out).not.toContain('Retry')
	})

	it('renders retryable with a Retry button', () => {
		q.state = { ...q.state, isError: true, error: new PublicCollectionError('retryable', 503) }
		const out = html()
		expect(out).toContain("We couldn't load these properties right now.")
		expect(out).toContain('Retry')
	})

	it('treats a non-PublicCollectionError as retryable', () => {
		q.state = { ...q.state, isError: true, error: new SyntaxError('bad json') }
		const out = html()
		expect(out).toContain('right now.')
		expect(out).toContain('Retry')
	})

	it('renders empty', () => {
		q.state = { ...q.state, data: { ...data, items: [] } }
		expect(html()).toContain('No properties in this collection yet.')
	})

	it('renders list with agent contact and noindex meta', () => {
		q.state = { ...q.state, data }
		const out = html()
		expect(out).toContain('Marina picks')
		expect(out).toContain('Sara Ali')
		expect(out).toContain('href="mailto:sara@example.com"')
		expect(out).toContain('href="tel:+971501234567"')
		expect(out).toContain('Sea view 2BR')
		expect(out).toContain('AED 2,500,000')
		expect(out).toContain('Listing details from Property Finder, updated')
		const head = render(Page).head
		expect(head).toContain('content="noindex,nofollow"')
		expect(head).toContain('name="referrer" content="no-referrer"')
	})

	it('unavailable item shows no price', () => {
		q.state = { ...q.state, data: { ...data, items: [{ status: 'unavailable' }] } }
		const out = html()
		expect(out).toContain('No longer available')
		expect(out).not.toContain('AED')
	})
})
