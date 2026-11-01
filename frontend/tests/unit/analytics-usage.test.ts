import { describe, expect, it } from 'vitest'
import { usageCountLabel, usageNote, usageTotal } from '../../src/lib/utils/analyticsUsage'

// An office tower used to show zeros under the residential-only view: the note must say what is
// shown and where the other usage's records are, so a zero is never unexplained.
const officeTower = { Residential: { sales: 0, leases: 0 }, Commercial: { sales: 49, leases: 50 } }
const mixed = { Residential: { sales: 322, leases: 341 }, Commercial: { sales: 9, leases: 29 } }

describe('analytics usage', () => {
	it('counts and labels each usage', () => {
		expect(usageTotal(officeTower, 'Commercial')).toBe(99)
		expect(usageCountLabel(officeTower, 'Commercial')).toBe('49 sales · 50 leases')
		expect(usageCountLabel(officeTower, 'Residential')).toBe('No records')
		expect(usageCountLabel({ Commercial: { sales: 1, leases: 0 } }, 'Commercial')).toBe('1 sale')
	})

	it('explains an automatic switch to commercial records', () => {
		expect(usageNote('Commercial', 'auto', officeTower)).toBe(
			'Showing commercial (offices, shops) records: this project has no residential sales or leases.'
		)
	})

	it('points to the other usage in a mixed project', () => {
		expect(usageNote('Residential', 'auto', mixed)).toBe(
			'Showing residential records. 38 commercial (offices, shops) records are under Commercial.'
		)
		expect(usageNote('Commercial', 'Commercial', mixed, 'this community')).toBe(
			'Showing commercial (offices, shops) records. 663 residential records are under Residential.'
		)
	})

	it('says when a chosen usage has no records', () => {
		expect(usageNote('Residential', 'Residential', officeTower)).toBe(
			'No residential sales or leases for this project.'
		)
	})
})
