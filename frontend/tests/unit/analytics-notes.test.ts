import { describe, expect, it } from 'vitest'
import {
	forecastNote,
	grossYieldPct,
	partialPeriodsNote,
	pipelineBasisNote
} from '../../src/lib/utils/analyticsNotes'

const providers = /\b(DLD|DXBI|DXBInteract|Dubai Land Department)\b/i

describe('analytics notes', () => {
	// The forecast used to answer an empty series the page drew as nothing at all.
	it('says when a forecast is not available', () => {
		const note = forecastNote({ available: false, data: [], methodology: '' })
		expect(note).toContain('not available')
		expect(note).not.toMatch(providers)
		expect(forecastNote({ available: true, data: [], methodology: '' })).toBeNull()
		expect(forecastNote(null)).toBeNull()
	})

	// A master's pipeline counts its area's projects, so its units differ from the master's own.
	it('names the area the pipeline counts', () => {
		const note = pipelineBasisNote({ area_name: 'Marsa Dubai', data: [] })
		expect(note).toBe(
			'Counts every registered project in Marsa Dubai, the area of this selection, not only its own projects.'
		)
		expect(note).not.toMatch(providers)
		expect(pipelineBasisNote({ area_name: 'Dubai', data: [] })).toBe(
			'Counts every registered project in Dubai.'
		)
	})

	// The yield card divided the cheapest rent by the cheapest sale price.
	it('computes the gross yield from median rent and median price', () => {
		expect(grossYieldPct({ median_annual_rent: 90_000 }, { median_price: 1_500_000 })).toBe(6)
		expect(grossYieldPct({ median_annual_rent: null }, { median_price: 1_500_000 })).toBeNull()
		expect(grossYieldPct(undefined, undefined)).toBeNull()
	})

	it('flags partial first and last periods', () => {
		expect(
			partialPeriodsNote([
				{ date: '2025-11-01', partial: true },
				{ date: '2025-12-01', partial: false },
				{ date: '2026-11-01', partial: true }
			])
		).toBe('The first and last periods are partial: the selected range cuts them.')
		expect(partialPeriodsNote([{ date: '2026-11-01', partial: true }])).toBe(
			'The last period is partial: the selected range cuts it.'
		)
		expect(partialPeriodsNote([{ date: '2026-11-01', partial: false }])).toBeNull()
	})
})
