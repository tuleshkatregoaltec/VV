import { describe, expect, it } from 'vitest'

import type { OwnerUnitCheck } from '$lib/crm/api/types'
import { matchLines } from '$lib/crm/ownerMatch'

/* Field comparisons must explain evidence without inventing a second ownership assessment. */
const check = (over: {
	imported?: Partial<OwnerUnitCheck['imported']>
	dld?: Partial<OwnerUnitCheck['dld']>
}): OwnerUnitCheck => ({
	imported: {
		date: '2024-02-27',
		aed: 1_100_000,
		type: 'Unit',
		unit: 'G01',
		role: 'Buyer',
		...over.imported
	},
	dld: {
		unit: 'G01',
		building: 'Al Ghozlan 4',
		area: 'Greens',
		date: '2024-02-27',
		aed: 1_100_000,
		type: 'Apartment',
		bedrooms: '1 Bed',
		size_sqft: 1042,
		built_up_sqft: null,
		aed_per_sqft: 1056,
		market: 'Ready',
		...over.dld
	},
	result: {
		label: 'Verified owner',
		confidence: 98,
		reason: '',
		chip: { tone: 'green', label: 'Verified owner' }
	},
	lease: null
})
const byLabel = (c: OwnerUnitCheck) => Object.fromEntries(matchLines(c).map((m) => [m.label, m]))

describe('matchLines', () => {
	it('marks a verified owner: same unit, same sale, price within 2%', () => {
		const m = byLabel(check({ imported: { aed: 1_110_000 } }))
		expect(m.Unit.result).toBe('match')
		expect(m['Sale date']).toMatchObject({ result: 'match', note: 'Same date' })
		expect(m.Price).toMatchObject({ result: 'match', note: 'Within 2%' })
		expect(m.Role.note).toBe('Source says Buyer; see ownership assessment')
		expect(m['Property type'].note).toBe('Compatible: Unit / Apartment')
	})

	it('shows a later sale without independently declaring the person a former owner', () => {
		const m = byLabel(
			check({
				imported: {
					date: '2024-03-25',
					aed: 2_060_000,
					type: 'Land',
					unit: 'JVT03B1TH066',
					role: 'Seller'
				},
				dld: { unit: 'jvt03b1th066', date: '2025-05-27', aed: 3_175_000, type: 'Villa' }
			})
		)
		expect(m.Unit.result).toBe('match')
		expect(m['Sale date']).toMatchObject({ result: 'differs' })
		expect(m['Sale date'].note).toContain('428 days after')
		expect(m['Sale date'].note).not.toContain('sold since')
		expect(m.Price.result).toBe('differs')
		expect(m['Property type']).toMatchObject({
			result: 'info',
			note: 'Different descriptions; see ownership assessment'
		})
		expect(m.Role.note).toBe('Source says Seller; role retained for review')
	})

	it('shows the matching amount despite the Park Heights source-date discrepancy', () => {
		const m = byLabel(
			check({
				imported: { date: '2024-03-27', aed: 858888 },
				dld: { date: '2018-09-27', aed: 858888 }
			})
		)
		expect(m.Price.result).toBe('match')
		expect(m['Sale date'].result).toBe('info')
		expect(m['Sale date'].note).toContain('2,008 days after')
	})

	it('a date inside the seven-day window supports comparison without proving the same sale', () => {
		const m = byLabel(check({ dld: { date: '2024-03-05' } }))
		expect(m['Sale date'].result).toBe('match')
		expect(m['Sale date'].note).toBe('Dates within 7 days; see ownership assessment')
		expect(m['Sale date'].note).not.toContain('Same sale')
	})

	it('flags a price that differs on the same sale', () => {
		const m = byLabel(check({ imported: { aed: 1_300_000 } }))
		expect(m.Price).toMatchObject({ result: 'differs', note: 'Differs by 18.2%' })
	})

	it('says when there is nothing to compare', () => {
		const m = byLabel(
			check({ imported: { role: '' }, dld: { unit: '', date: null, aed: null, type: '' } })
		)
		expect(m.Unit.note).toBe('No DLD sale found for this unit')
		expect(m['Sale date'].result).toBe('none')
		expect(m.Price.result).toBe('none')
		expect(m.Role.note).toBe('No role in the file')
	})
})
