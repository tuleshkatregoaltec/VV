import { describe, expect, it } from 'vitest'

import { budgetBand } from '$lib/crm/budgetBand'

// Portal listings are matched inside a band around the buyer's budget (backend matching_policy.py:
// 30% below to 20% above). The lead's Matches tab and the Matches page state that band, so the
// agent knows which prices the list holds.
describe('budget band', () => {
	it('runs from 30% below to 20% above the budget', () => {
		expect(budgetBand(3_000_000)).toEqual({ low: 2_100_000, high: 3_600_000 })
		expect(budgetBand(1_050_000)).toEqual({ low: 735_000, high: 1_260_000 })
	})

	it('has no band without a budget', () => {
		expect(budgetBand(0)).toBeNull()
	})
})
