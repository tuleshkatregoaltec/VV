import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import type { CrmCompanyListingDetail } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '$lib/crm/api'

const DETAIL: CrmCompanyListingDetail = {
	reference: 'PF-123',
	listing_key: '123',
	agent_name: 'Big Firm · Navi',
	agent_phone: null,
	mode: 'sale',
	title: 'Marina Gate 2BR',
	property_type: 'Apartment',
	bedrooms: 2,
	size_sqft: 1200,
	price_aed: 2_500_000,
	area_name: 'Dubai Marina',
	building_name: 'Marina Gate',
	unit_number: null,
	status: 'active',
	listed_at: new Date().toISOString(),
	broker_id: 'B1',
	broker_name: 'Big Firm',
	managed: true
}

afterEach(() => vi.restoreAllMocks())

describe('listing detail', () => {
	it('loads a company listing by its Property Finder id', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue(DETAIL)

		const listing = await crm.listings.get('PF-123')

		expect(get).toHaveBeenCalledWith('/api/v1/crm/company-listings/123')
		expect(listing).toMatchObject({
			id: 'PF-123',
			unit: 'Marina Gate 2BR',
			scope: 'company',
			managed: true,
			listing_key: '123',
			can_publish: false
		})
		expect(listing.leads).toEqual([])
	})

	it('accepts real Property Finder ids (26 letters and digits)', async () => {
		const get = vi
			.spyOn(client, 'get')
			.mockResolvedValue({ ...DETAIL, reference: 'PF-E4PE3H23YAHTAQDKRCMSMVTDK4' })

		await crm.listings.get('PF-E4PE3H23YAHTAQDKRCMSMVTDK4')

		expect(get).toHaveBeenCalledWith('/api/v1/crm/company-listings/E4PE3H23YAHTAQDKRCMSMVTDK4')
	})

	it('keeps other listings unavailable instead of inventing them', async () => {
		const get = vi.spyOn(client, 'get')
		await expect(crm.listings.get('L-9')).rejects.toThrow()
		expect(get).not.toHaveBeenCalled()
	})
})

describe('documents', () => {
	it('sends the idempotency key it was given, unchanged', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({})
		const key = '6f1d3c1e-8a7b-4c33-9b1a-2f0e5d4c3b2a'

		await crm.documents.generate({
			source: 'property_finder',
			listing_key: '123',
			doc_type: 'noc',
			expected_revision: 1,
			idempotency_key: key
		})

		expect(post).toHaveBeenCalledWith(
			'/api/v1/crm/documents',
			expect.objectContaining({ idempotency_key: key })
		)
	})

	it('filters the document list through the query string', async () => {
		const get = vi
			.spyOn(client, 'get')
			.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 })

		await crm.documents.list({
			listingKey: '123',
			docType: 'lease',
			search: ' marina ',
			offset: 50
		})

		const url = new URL(`http://x${get.mock.calls[0][0]}`)
		expect(url.pathname).toBe('/api/v1/crm/documents')
		expect(Object.fromEntries(url.searchParams)).toEqual({
			listing_key: '123',
			doc_type: 'lease',
			search: 'marina',
			offset: '50'
		})
	})

	it('asks for a fresh download link each time', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ url: 'u', expires_at: '' })

		await crm.documents.download('d-1')
		await crm.documents.download('d-1')

		expect(post).toHaveBeenCalledTimes(2)
		expect(post).toHaveBeenCalledWith('/api/v1/crm/documents/d-1/download', {})
	})

	it('asks for a preview link that opens in the browser', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ url: 'u', expires_at: '' })

		await crm.documents.preview('d-1')

		expect(post).toHaveBeenCalledWith('/api/v1/crm/documents/d-1/download?inline=true', {})
	})
})
