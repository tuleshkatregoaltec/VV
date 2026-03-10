import { beforeEach, describe, expect, it, vi } from 'vitest'

// Mock the feasibility store before importing currency utils,
// since currency.ts reads from it at import time via module-level references.
vi.mock('$lib/stores/feasibility.svelte', () => ({
	feasibilityStore: {
		displayCurrency: 'AED',
		fxRateAEDtoUSD: 3.67
	}
}))

import { feasibilityStore } from '$lib/stores/feasibility.svelte'
import {
	currencySymbol,
	displayK,
	displayValue,
	fromSqft,
	SQM_PER_SQFT,
	toSqft
} from '$lib/utils/currency'

// Cast to allow mutation in tests
const store = feasibilityStore as { displayCurrency: string; fxRateAEDtoUSD: number }

beforeEach(() => {
	store.displayCurrency = 'AED'
	store.fxRateAEDtoUSD = 3.67
})

describe('displayValue', () => {
	it('returns AED value unchanged when currency is AED', () => {
		expect(displayValue(1000)).toBe(1000)
	})

	it('converts AED to USD by dividing by fx rate', () => {
		store.displayCurrency = 'USD'
		expect(displayValue(367)).toBeCloseTo(100)
	})
})

describe('currencySymbol', () => {
	it('returns AED when currency is AED', () => {
		expect(currencySymbol()).toBe('AED')
	})

	it('returns USD when currency is USD', () => {
		store.displayCurrency = 'USD'
		expect(currencySymbol()).toBe('USD')
	})
})

describe('displayK', () => {
	it('formats millions as thousands (k)', () => {
		expect(displayK(1_000_000)).toBe('1,000')
	})

	it('formats negative values with brackets', () => {
		expect(displayK(-500_000)).toBe('(500)')
	})

	it('rounds to nearest thousand', () => {
		expect(displayK(1_499_000)).toBe('1,499')
		expect(displayK(1_500_000)).toBe('1,500')
	})

	it('handles zero', () => {
		expect(displayK(0)).toBe('0')
	})

	it('formats in USD when currency is USD', () => {
		store.displayCurrency = 'USD'
		// 3_670_000 AED / 3.67 = 1,000,000 USD -> displayed as 1,000 (k)
		expect(displayK(3_670_000)).toBe('1,000')
	})
})

describe('area conversions', () => {
	it('SQM_PER_SQFT is approximately 0.0929', () => {
		expect(SQM_PER_SQFT).toBeCloseTo(0.092903)
	})

	it('toSqft converts sqm to sqft', () => {
		expect(toSqft(1)).toBeCloseTo(10.764, 1)
	})

	it('fromSqft converts sqft to sqm', () => {
		expect(fromSqft(10.764)).toBeCloseTo(1, 1)
	})

	it('toSqft and fromSqft are inverse operations', () => {
		const original = 150
		expect(fromSqft(toSqft(original))).toBeCloseTo(original)
	})
})
