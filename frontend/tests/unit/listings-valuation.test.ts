import { describe, expect, it } from 'vitest'

import type { ListingCardResponse } from '$lib/api/listings'
import { basisText, dataAgeText, valueLabel, valueTone } from '$lib/listings/valuation'

/* Market › Listings shows each sale listing against DLD sales of the same bedroom count in the same
   building (Kian, 11 Nov 2026: the old asking-price benchmark was "grossly inaccurate"). The labels
   must say where a number comes from, and never present a suppressed estimate as a bargain. */
const card = (extra: Partial<ListingCardResponse>) =>
	({
		listing_mode: 'sale',
		market_position: 'insufficient_data',
		market_delta_pct: null,
		comparable_count: 0,
		valuation_method: 'dld_sales',
		valuation_confidence: null,
		value_gap_pct: null,
		is_off_plan: false,
		...extra
	}) as ListingCardResponse

describe('value label', () => {
	it('names the discount to the DLD estimate', () => {
		expect(valueLabel(card({ market_position: 'below_market', value_gap_pct: -0.123 }))).toBe(
			'12.3% below value'
		)
	})

	it('says "asking above sales", not "overpriced": asking prices usually sit above sale prices', () => {
		expect(valueLabel(card({ market_position: 'above_market', value_gap_pct: 0.15 }))).toBe(
			'Asking 15.0% above sales'
		)
		expect(valueTone(card({ market_position: 'above_market' }))).toContain('warning')
	})

	it('treats a listing inside the range as at value', () => {
		expect(valueLabel(card({ market_position: 'near_market', value_gap_pct: 0.02 }))).toBe(
			'At value'
		)
	})

	it('never shows a bargain without enough same-bedroom sales', () => {
		expect(valueLabel(card({ market_position: 'insufficient_data' }))).toBe('Not enough sales')
		expect(valueTone(card({ market_position: 'insufficient_data' }))).toContain('fg-4')
	})

	it('marks off-plan sale listings as not valued', () => {
		expect(valueLabel(card({ is_off_plan: true, valuation_method: 'asking_peers' }))).toBe(
			'Off-plan · not valued'
		)
	})

	it('keeps the asking-price comparison wording for rent', () => {
		const rent = card({
			listing_mode: 'rent',
			valuation_method: 'asking_peers',
			market_position: 'below_market',
			market_delta_pct: -0.08
		})
		expect(valueLabel(rent)).toBe('8.0% below')
	})
})

describe('basis text', () => {
	it('counts the DLD sales behind the estimate and its confidence', () => {
		expect(
			basisText(
				card({ market_position: 'below_market', comparable_count: 5, valuation_confidence: 'high' })
			)
		).toBe('5 recorded sales · high confidence')
	})

	it('explains a missing estimate', () => {
		expect(basisText(card({}))).toBe('Too few same-bedroom sales in this building')
		expect(basisText(card({ is_off_plan: true, valuation_method: 'asking_peers' }))).toBe(
			'No ready sales to compare with'
		)
	})

	it('keeps peer-listing wording for the asking-price comparison', () => {
		expect(
			basisText(
				card({ listing_mode: 'rent', valuation_method: 'asking_peers', comparable_count: 7 })
			)
		).toBe('7 peer listings')
	})
})

describe('data age', () => {
	it('tells the user when the listings were collected', () => {
		expect(dataAgeText('2026-05-27T13:19:20+00:00')).toBe('Listings collected 27 May 2026')
		expect(dataAgeText(null)).toBeNull()
	})
})
