import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { listOwners } from '$lib/crm/api/backend'
import { crmQueries } from '$lib/crm/queries'
import { ui } from '$lib/crm/stores/ui.svelte'

/* The Owners page pages through the whole agency file (73k owners), 500 at a time. */
const owner = (key: string) => ({
	owner_key: key,
	contact_name: key.toUpperCase(),
	highest_ownership_status: 'verified_current_owner',
	properties: []
})

function mockBackend(total: number, owners = [owner('a'), owner('b')]) {
	return vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		if (url.includes('/owner-workspaces')) return [] as never
		return { owners, total, limit: 500, offset: 500, summary: {} } as never
	})
}

afterEach(() => vi.restoreAllMocks())

describe('listOwners paging', () => {
	it('asks the backend for the requested page', async () => {
		const get = mockBackend(73224)
		await listOwners({ tab: 'all', offset: 500 })
		const registryUrl = get.mock.calls.map(([u]) => u).find((u) => u.includes('/owner-registry'))
		expect(registryUrl).toContain('offset=500')
		expect(registryUrl).toContain('limit=500')
	})

	it('reports where the page sits in the whole file', async () => {
		mockBackend(73224)
		const res = await listOwners({ tab: 'all', offset: 500 })
		expect(res.page).toEqual({ offset: 500, limit: 500, total: 73224, loaded: 2 })
	})

	it('reports the complete server total when no page-only filter is set', async () => {
		mockBackend(73224)
		const res = await listOwners({ tab: 'all', offset: 0 })
		expect(res.page.total).toBe(73224)
		expect(res.pageFiltered).toBe(false)
	})

	it('marks unsupported filters as limited to the page without replacing the server total', async () => {
		mockBackend(73224)
		const res = await listOwners({ tab: 'all', offset: 0, area: 'JVC' })
		expect(res.items).toHaveLength(0)
		expect(res.page.total).toBe(73224)
		expect(res.pageFiltered).toBe(true)
	})

	it('starts at the first page when no offset is given', async () => {
		const get = mockBackend(10)
		await listOwners({ tab: 'all' })
		const registryUrl = get.mock.calls.map(([u]) => u).find((u) => u.includes('/owner-registry'))
		expect(registryUrl).toContain('offset=0')
	})
})

/* Every tab the backend can filter (All, Just sold, 3+ units, Next event) counts the whole file. */
function mockFile({
	all = 73224,
	sold = 900,
	multi = 1187,
	event = 9086,
	review = 37,
	workspaces = 3
} = {}) {
	return vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		if (url.includes('/owner-workspaces'))
			return Array.from({ length: workspaces }, (_, i) => ({ owner_key: `w${i}` })) as never
		const total = url.includes('scope=needs_review')
			? review
			: url.includes('scope=prior_owners')
				? sold
				: url.includes('min_properties=3')
					? multi
					: url.includes('next_event_days=90')
						? event
						: all
		return { owners: [owner('a'), owner('b')], total, limit: 500, offset: 0, summary: {} } as never
	})
}
const registryUrls = (get: ReturnType<typeof mockFile>) =>
	get.mock.calls.map(([u]) => u).filter((u) => u.includes('/owner-registry'))

describe('listOwners tab counts across the whole file', () => {
	it('lists Just sold from every former owner, paged', async () => {
		const get = mockFile()
		const res = await listOwners({ tab: 'sold', offset: 500 })
		const main = registryUrls(get).find((u) => u.includes('offset=500'))
		expect(main).toContain('scope=prior_owners')
		expect(res.page.total).toBe(900)
		expect(res.items).toHaveLength(2)
	})

	it('lists 3+ units from every owner with at least 3 units, paged', async () => {
		const get = mockFile()
		const res = await listOwners({ tab: 'multi', offset: 500 })
		const main = registryUrls(get).find((u) => u.includes('offset=500'))
		expect(main).toContain('min_properties=3')
		expect(res.page.total).toBe(1187)
		expect(res.items).toHaveLength(2)
	})

	it('lists Next event from every owner whose lease ends within 90 days, paged', async () => {
		const get = mockFile()
		const res = await listOwners({ tab: 'event', offset: 500 })
		const main = registryUrls(get).find((u) => u.includes('offset=500'))
		expect(main).toContain('next_event_days=90')
		expect(res.page.total).toBe(9086)
	})

	it('requests only the visible registry page while preserving each backend tab total', async () => {
		const get = mockFile()
		const totals = { all: 73224, sold: 900, multi: 1187, event: 9086 }
		for (const tab of ['all', 'sold', 'multi', 'event'] as const) {
			const res = await listOwners({ tab, offset: 0 })
			expect(res.page.total).toBe(totals[tab])
		}
		expect(registryUrls(get)).toHaveLength(4)
	})

	it('keeps My contacts explicitly limited to this page', async () => {
		mockFile({ workspaces: 3 })
		const res = await listOwners({ tab: 'mine', offset: 0 })
		expect(res.pageFiltered).toBe(true)
		expect(res.items).toHaveLength(0)
	})

	it('does not expose unused aggregates that would require extra registry reads', async () => {
		mockFile()
		const res = await listOwners({ tab: 'all', offset: 0 })
		expect(res).not.toHaveProperty('counts')
		expect(res).not.toHaveProperty('on_file')
	})
})

describe('listOwners page size', () => {
	it('opens the Owners table with ten rows and sends that size through the typed query', async () => {
		const get = mockFile()
		expect(ui.ownerPageSize).toBe(10)
		const res = await crmQueries
			.owners({ tab: 'all', offset: 0, limit: ui.ownerPageSize })
			.queryFn()
		expect(registryUrls(get)[0]).toContain('limit=10')
		expect(registryUrls(get)[0]).toContain('offset=0')
		expect(res.page.limit).toBe(10)
	})

	it('requests ten-row pages at the next and previous offsets', async () => {
		const get = mockFile()
		for (const offset of [0, 10, 0]) {
			const res = await crmQueries.owners({ tab: 'all', offset, limit: 10 }).queryFn()
			expect(res.page).toMatchObject({ offset, limit: 10, total: 73224 })
		}
		const pages = registryUrls(get)
			.map((url) => new URL(url, 'https://example.test').searchParams)
			.filter((params) => params.get('limit') === '10')
		expect(pages.map((params) => params.get('offset'))).toEqual(['0', '10', '0'])
	})

	it('asks the backend for the chosen number of owners per page', async () => {
		const get = mockFile()
		const res = await listOwners({ tab: 'all', offset: 100, limit: 50 })
		const main = registryUrls(get).find((u) => u.includes('offset=100'))
		expect(main).toContain('limit=50')
		expect(res.page.limit).toBe(50)
	})

	it('keeps 500 per page when no size is given', async () => {
		const get = mockFile()
		const res = await listOwners({ tab: 'all', offset: 0 })
		expect(registryUrls(get)[0]).toContain('limit=500')
		expect(res.page.limit).toBe(500)
	})
})

describe('unresolved evidence review queue', () => {
	it('requests the server review scope so unresolved people beyond the first page are actionable', async () => {
		const get = mockFile({ review: 37 })
		const res = await listOwners({ tab: 'review', offset: 25, limit: 25, list_id: 12 })
		const main = registryUrls(get).find((url) => url.includes('offset=25'))
		expect(main).toContain('scope=needs_review')
		expect(main).toContain('list_id=12')
		expect(res.page.total).toBe(37)
		expect(res.pageFiltered).toBe(false)
		for (const url of registryUrls(get)) expect(url).toContain('list_id=12')
	})
})

// Ownership is filtered by the server before paging, including portfolio counts.
describe('current and former ownership filters', () => {
	it.each([
		['current', 'current_owners'],
		['former', 'prior_owners']
	] as const)('requests all %s owners without an extra former-owner tier', async (ownership, scope) => {
		const get = mockFile()
		await listOwners({ tab: 'multi', ownership, offset: 500 })
		const main = registryUrls(get).find((url) => url.includes('offset=500'))
		expect(main).toContain(`scope=${scope}`)
		expect(main).toContain('min_properties=3')
	})
})

describe('transaction matching filters', () => {
	it('sends the property matching filter for the main page and all tab totals', async () => {
		const get = mockFile()
		await listOwners({
			tab: 'all',
			ownership: 'former',
			transaction_match_status: 'unmatched',
			offset: 50,
			limit: 10
		})
		const urls = registryUrls(get)
		expect(urls.every((u) => u.includes('transaction_match_status=unmatched'))).toBe(true)
		expect(urls.find((u) => u.includes('offset=50'))).toContain('scope=prior_owners')
	})
})
