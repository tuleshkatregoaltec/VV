import { QueryClient } from '@tanstack/svelte-query'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { getOwnerHistory, getOwnerHistorySummary } from '$lib/crm/api/backend'
import { crmKeys, crmQueries } from '$lib/crm/queries'

afterEach(() => vi.restoreAllMocks())

describe('owner history uses canonical source and association counts', () => {
	it('loads an organization summary separately from an import summary', async () => {
		const summary = {
			source_event_count: 7,
			identifiable_property_count: 1,
			owner_property_count: 2,
			verified_current_count: 0,
			probable_current_count: 1,
			former_count: 1,
			unresolved_count: 0,
			invalid_identity_source_count: 1,
			legacy_source_event_count: 2,
			resolver_versions: { v2: 5 }
		}
		const get = vi.spyOn(client, 'get').mockResolvedValue(summary)
		expect(await getOwnerHistorySummary()).toEqual(summary)
		expect(await getOwnerHistorySummary(12)).toEqual(summary)
		expect(get.mock.calls.map(([url]) => url)).toEqual([
			'/api/v1/crm/owner-history/summary',
			'/api/v1/crm/contact-imports/12/owner-summary'
		])
	})

	it('requests each history page and optional import scope without changing event evidence', async () => {
		const response = {
			owner_key: 'name/phone',
			events: [
				{
					id: 7,
					party_role: 'Seller',
					procedure_type: 'Mortgage',
					observed_ownership_status: 'probable_current_owner',
					current_ownership_status: 'unmatched',
					property_key: null,
					source_filename: 'older.csv',
					source_sheet: 'Sheet1',
					source_row_number: 8
				}
			],
			total: 51,
			limit: 25,
			offset: 25
		}
		const get = vi.spyOn(client, 'get').mockResolvedValue(response)
		expect(await getOwnerHistory('name/phone', { import_id: 12, limit: 25, offset: 25 })).toEqual(
			response
		)
		expect(get).toHaveBeenCalledWith(
			'/api/v1/crm/owners/name%2Fphone/history?limit=25&offset=25&import_id=12'
		)
	})

	it('defaults to the first page and keeps different owners, pages and imports in separate caches', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ events: [] })
		await crmQueries.ownerHistory('owner-a').queryFn()
		expect(get).toHaveBeenCalledWith('/api/v1/crm/owners/owner-a/history?limit=50&offset=0')
		expect(crmKeys.ownerHistory('owner-a', { offset: 0 })).not.toEqual(
			crmKeys.ownerHistory('owner-a', { offset: 25 })
		)
		expect(crmKeys.ownerHistory('owner-a', {})).not.toEqual(crmKeys.ownerHistory('owner-b', {}))
		expect(crmKeys.ownerHistorySummary()).not.toEqual(crmKeys.ownerHistorySummary(12))
	})

	it('refreshes every history and summary cache when imports, replay or deletion invalidate CRM', async () => {
		const cache = new QueryClient()
		const keys = [
			crmKeys.ownerHistory('owner-a', { offset: 0 }),
			crmKeys.ownerHistory('owner-a', { offset: 25 }),
			crmKeys.ownerHistorySummary(),
			crmKeys.ownerHistorySummary(12)
		]
		for (const key of keys) cache.setQueryData(key, { previous: true })
		await cache.invalidateQueries({ queryKey: crmKeys.all })
		for (const key of keys) expect(cache.getQueryState(key)?.isInvalidated).toBe(true)
		cache.clear()
	})
})
