import { describe, expect, it } from 'vitest'
import { formatDataAsOf } from '$lib/feasibility/format'
import { buildPricingEvidenceStudy } from '$lib/feasibility/view-models'

describe('feasibility data-as-of label', () => {
	it('names the source and the date of its latest record', () => {
		expect(formatDataAsOf({ source: 'dxbi', as_of: '2026-11-14' })).toBe('DXBI · as of 14 Nov 2026')
		expect(formatDataAsOf({ source: 'dld', as_of: '2026-10-13' })).toBe('DLD · as of 13 Oct 2026')
	})

	it('says so when a source has no record for the area', () => {
		expect(formatDataAsOf({ source: 'dld', as_of: null })).toBe('DLD · no records for this area')
	})

	it('does not shift the date with the viewer time zone', () => {
		expect(formatDataAsOf({ source: 'dxbi', as_of: '2026-01-01' })).toBe('DXBI · as of 1 Jan 2026')
	})

	it('reaches the pricing evidence sheet', () => {
		const study = buildPricingEvidenceStudy(
			{
				market_area: 'Marsa Dubai',
				usage: 'residential',
				headline: 'h',
				data_as_of: [
					{ key: 'market_pricing', label: 'Sales pricing', source: 'dxbi', as_of: '2026-11-14' }
				]
			} as never,
			null
		)
		expect(study?.data_as_of).toEqual([
			{ key: 'market_pricing', label: 'Sales pricing', source: 'dxbi', as_of: '2026-11-14' }
		])
	})
})
