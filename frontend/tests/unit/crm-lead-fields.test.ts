import { describe, expect, it } from 'vitest'

import { fieldShown, LEAD_TYPES } from '$lib/crm/config'

// Bedrooms only mean something for homes. The forms ask for them when Wants is a home type
// (or not chosen yet) and hide them for offices, shops, warehouses, land and the like.
const field = (key: string) => {
	const f = LEAD_TYPES.buyer.fields.find((x) => x.key === key)
	if (!f) throw new Error(`No buyer field ${key}`)
	return f
}
const bedrooms = field('bedrooms')
const budget = field('budget_aed')

describe('Bedrooms field', () => {
	it('shows for home types', () => {
		for (const wants of ['Apartment', 'Villa', 'Townhouse', 'Penthouse', 'Duplex', 'Bungalow']) {
			expect(fieldShown(bedrooms, { wants })).toBe(true)
		}
	})

	it('shows while no type is chosen yet', () => {
		expect(fieldShown(bedrooms, { wants: '' })).toBe(true)
		expect(fieldShown(bedrooms, {})).toBe(true)
	})

	it('hides for types without bedrooms', () => {
		for (const wants of ['Office Space', 'Shop', 'Warehouse', 'Land', 'Whole Building']) {
			expect(fieldShown(bedrooms, { wants })).toBe(false)
		}
	})

	it('never hides other fields', () => {
		expect(fieldShown(budget, { wants: 'Office Space' })).toBe(true)
	})
})
