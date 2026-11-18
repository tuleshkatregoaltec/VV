import { describe, expect, it } from 'vitest'

import type { ListingCard } from '$lib/crm/api/types'
import { PROPERTY_TYPES } from '$lib/crm/config'
import { optionPicks, unitPicks } from '$lib/crm/stagePickers'

/* Moving a lead to Viewing / Offer / Won asks which unit. The agency and company lists hold
   hundreds of listings, so the picker searches and puts the units that fit the lead first, and
   each row says where, what and how much, not just the portal headline. */
const listing = (extra: Partial<ListingCard>) =>
	({
		id: 'L',
		unit: 'Large Layout | ARA | Park Location',
		area: 'Tilal Al Ghaf',
		bedrooms: 3,
		price_aed: 3_000_000,
		deal_type: 'sale',
		scope: 'company',
		...extra
	}) as ListingCard

describe('unit picker', () => {
	it('shows the area, bedrooms, price and whose listing on every row', () => {
		const [row] = unitPicks([listing({ id: 'A', scope: 'mine' })], {
			area: '',
			budget: null
		})
		expect(row).toEqual({
			id: 'A',
			label: 'Large Layout | ARA | Park Location',
			meta: 'Tilal Al Ghaf · 3BR · AED 3.0M · Your listing'
		})
	})

	it("puts units in the lead's area first, then those within budget", () => {
		const rows = unitPicks(
			[
				listing({
					id: 'far-cheap',
					area: 'Dubai Marina',
					price_aed: 1_000_000
				}),
				listing({
					id: 'area-pricey',
					area: 'Town Square',
					price_aed: 9_000_000
				}),
				listing({ id: 'area-fits', area: 'Town Square', price_aed: 1_900_000 }),
				listing({
					id: 'far-pricey',
					area: 'Palm Jumeirah',
					price_aed: 9_000_000
				})
			],
			{ area: 'Town Square', budget: 2_000_000 }
		)
		expect(rows.map((r) => r.id)).toEqual(['area-fits', 'area-pricey', 'far-cheap', 'far-pricey'])
	})

	it('labels studios and rents plainly', () => {
		const [row] = unitPicks([listing({ bedrooms: 0, price_aed: 95_000, deal_type: 'rent' })], {
			area: '',
			budget: null
		})
		expect(row.meta).toBe('Tilal Al Ghaf · Studio · AED 95k a year · Company')
	})
})

describe('property type picker', () => {
	it('lists home types first and says which group each type is in', () => {
		const rows = optionPicks('wants', PROPERTY_TYPES)
		expect(rows[0]).toEqual({
			id: 'Apartment',
			label: 'Apartment',
			meta: 'Home'
		})
		expect(rows.find((r) => r.id === 'Office Space')?.meta).toBe('Commercial')
		expect(rows.find((r) => r.id === 'Land')?.meta).toBe('Industrial & land')
		expect(rows).toHaveLength(PROPERTY_TYPES.length)
	})

	it('leaves other option lists unlabelled', () => {
		expect(optionPicks('purpose', ['Live in', 'Invest'])).toEqual([
			{ id: 'Live in', label: 'Live in' },
			{ id: 'Invest', label: 'Invest' }
		])
	})
})
