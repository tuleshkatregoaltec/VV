import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '$lib/api/client'
import { crm } from '$lib/crm/api'
import { DOC_TYPES, fieldLabel, generate } from '$lib/crm/components/documents/documentRules'

afterEach(() => vi.restoreAllMocks())

const READY = { id: 'd-1', status: 'ready' } as never

describe('field labels', () => {
	it('names a missing field the way the form labels it', () => {
		expect(fieldLabel('owner.title_deed_number')).toBe('Title deed number')
		expect(fieldLabel('lease.annual_rent_aed')).toBe('Annual rent (AED)')
		expect(fieldLabel('listing.price_aed')).toBe('Listing price')
	})

	it('falls back to the path for a field it does not know', () => {
		expect(fieldLabel('owner.new_field')).toBe('owner.new_field')
	})

	it('offers the three documents in the reference order', () => {
		expect(DOC_TYPES.map((d) => d.label)).toEqual(['NOC', 'Lease Agreement', 'A2A Agreement'])
	})
})

describe('generate', () => {
	it('retries a dropped connection once with the same key, so the PDF is made once', async () => {
		const call = vi
			.spyOn(crm.documents, 'generate')
			.mockRejectedValueOnce(new ApiError('offline', 0, 'network_error'))
			.mockResolvedValueOnce(READY)

		const outcome = await generate('123', 'noc', 2)

		expect(outcome).toEqual({ ok: true, document: READY })
		const keys = call.mock.calls.map(([body]) => body.idempotency_key)
		expect(keys).toHaveLength(2)
		expect(keys[0]).toBe(keys[1])
		expect(call.mock.calls[0][0]).toMatchObject({
			listing_key: '123',
			doc_type: 'noc',
			expected_revision: 2
		})
	})

	it('lists missing details by their labels', async () => {
		vi.spyOn(crm.documents, 'generate').mockRejectedValue(
			new ApiError('', 422, 'missing_fields', {
				detail: { code: 'missing_fields', fields: ['owner.title_deed_number', 'owner.id_number'] }
			})
		)

		expect(await generate('123', 'noc', 1)).toEqual({
			ok: false,
			kind: 'missing',
			fields: ['Title deed number', 'Emirates ID / passport number']
		})
	})

	it('reports information changed by someone else', async () => {
		vi.spyOn(crm.documents, 'generate').mockRejectedValue(new ApiError('stale_revision', 409))
		expect(await generate('123', 'noc', 1)).toEqual({ ok: false, kind: 'stale' })
	})

	it('reports a failed PDF without retrying it', async () => {
		const call = vi
			.spyOn(crm.documents, 'generate')
			.mockRejectedValue(new ApiError('', 502, 'render_failed'))
		expect(await generate('123', 'lease', 1)).toEqual({ ok: false, kind: 'failed' })
		expect(call).toHaveBeenCalledTimes(1)
	})
})

describe('grouping for CRM › Documents', () => {
	const d = (id: string, listing_key: string, company_name: string | null, created_at: string) =>
		({
			id,
			listing_key,
			listing_title: `Listing ${listing_key}`,
			listing_area: 'Marina',
			company_name,
			created_at
		}) as never

	it('groups company → property → documents, most recent activity first', async () => {
		const { groupDocuments } = await import('$lib/crm/components/documents/documentRules')
		const groups = groupDocuments([
			d('d4', 'B', 'White & Co', '2026-11-12T10:00:00Z'),
			d('d3', 'A', 'White & Co', '2026-11-12T09:00:00Z'),
			d('d2', 'C', 'Big Firm', '2026-11-11T09:00:00Z'),
			d('d1', 'B', 'White & Co', '2026-11-10T09:00:00Z')
		])

		expect(groups.map((g) => g.company)).toEqual(['White & Co', 'Big Firm'])
		expect(groups[0].properties.map((p) => [p.listingKey, p.documents.map((x) => x.id)])).toEqual([
			['B', ['d4', 'd1']],
			['A', ['d3']]
		])
		expect(groups[0].properties[0]).toMatchObject({ title: 'Listing B', area: 'Marina' })
	})

	it('puts documents without a recorded company under one honest heading', async () => {
		const { groupDocuments } = await import('$lib/crm/components/documents/documentRules')
		expect(groupDocuments([d('d1', 'A', null, '2026-11-12T10:00:00Z')])[0].company).toBe(
			'Company not recorded'
		)
	})
})
