import { describe, expect, it } from 'vitest'
import {
	AREA_UNIT,
	formatAedPerSqft,
	formatSqft,
	fromSqft,
	PRICE_PER_AREA_UNIT,
	perSqft,
	perSqm,
	SQFT_TO_SQM,
	SQM_TO_SQFT,
	toSqft
} from '$lib/utils/units'

describe('square feet everywhere', () => {
	it('uses the shared market conversion factor, the same as the backend', () => {
		expect(SQM_TO_SQFT).toBe(10.7639)
		expect(SQM_TO_SQFT * SQFT_TO_SQM).toBeCloseTo(1)
	})

	it('labels every area in sq ft and every rate in AED/sq ft', () => {
		expect(AREA_UNIT).toBe('sq ft')
		expect(PRICE_PER_AREA_UNIT).toBe('AED/sq ft')
	})

	it('converts areas: 100 m² is 1,076 sq ft, and back', () => {
		expect(toSqft(100)).toBeCloseTo(1076.39)
		expect(fromSqft(toSqft(123.45))).toBeCloseTo(123.45)
	})

	it('converts rates the other way: AED 10,763.9 per m² is AED 1,000 per sq ft', () => {
		expect(perSqft(10_763.9)).toBeCloseTo(1_000)
		expect(perSqm(perSqft(15_000))).toBeCloseTo(15_000)
	})

	it('keeps the total unchanged: area x rate is the same in either unit', () => {
		const sqm = 85
		const aedPerSqm = 18_000
		expect(toSqft(sqm) * perSqft(aedPerSqm)).toBeCloseTo(sqm * aedPerSqm)
	})

	it('formats whole numbers identically in every locale and marks missing values', () => {
		expect(formatSqft(1250.4)).toBe('1,250')
		expect(formatAedPerSqft(1857.6)).toBe('1,858')
		expect(formatSqft(null)).toBe('-')
		expect(formatAedPerSqft(Number.NaN)).toBe('-')
	})
})
