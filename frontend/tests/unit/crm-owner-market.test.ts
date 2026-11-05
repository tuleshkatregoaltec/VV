import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { getOwner } from '$lib/crm/api/backend'

/* The owner panel's Market range shows today's estimated value of each unit (client call,
   5 Nov 2026): the agent sees what the home is worth now next to what the owner paid. */
const unit = (extra: Record<string, unknown>) => ({
	property_key: 'reem|187',
	building_name: 'Reem Townhouses',
	project_name: '',
	area_name: 'Town Square',
	unit_number: '187',
	property_type: 'Villa',
	ownership_status: 'verified_current_owner',
	confidence_score: 98,
	match_reason: '',
	latest_sale_price_aed: 2_365_000,
	source_lists: [],
	source_rows: [],
	...extra
})

function serve(properties: ReturnType<typeof unit>[]) {
	vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		if (url.startsWith('/api/v1/crm/owner-workspaces')) return [] as never
		if (url.startsWith('/api/v1/crm/contact-imports')) return [] as never
		if (url.startsWith('/api/v1/crm/owners/'))
			return {
				owner_key: 'omar',
				contact_name: 'Owner Example',
				highest_ownership_status: 'verified_current_owner',
				properties
			} as never
		throw new Error(`unexpected GET ${url}`)
	})
}

afterEach(() => vi.restoreAllMocks())

describe('owner market range', () => {
	it('maps the estimate to the sale range, with no rent range', async () => {
		serve([
			unit({
				estimated_value_aed: 2_687_000,
				estimated_value_low_aed: 2_576_000,
				estimated_value_high_aed: 2_901_000,
				valuation_confidence: 'low',
				valued_at: '2026-11-05'
			})
		])
		const o = await getOwner('omar')
		expect(o.unit_rows[0].market).toEqual({
			sale: [2_576_000, 2_901_000],
			rent: null,
			estimate: 2_687_000,
			confidence: 'low',
			valued_at: '2026-11-05'
		})
	})

	it('leaves the range empty when the unit has no estimate', async () => {
		serve([unit({})])
		const o = await getOwner('omar')
		expect(o.unit_rows[0].market).toBeNull()
	})
})
