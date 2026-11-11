import { describe, expect, it } from 'vitest'

import type { LeadRow } from '$lib/crm/api/types'
import { canDrop, columnTotal, compactAed, initials, needLine } from '$lib/crm/board'

const lead = (o: Partial<LeadRow> = {}): LeadRow =>
	({
		id: 1,
		name: 'Ashwin Vyas',
		lead_type: 'buyer',
		deal_type: 'sale',
		stage: 'qualified',
		gated: false,
		fields: {},
		summary: { line: 'Not stated', sub: '' },
		...o
	}) as LeadRow

describe('leads board', () => {
	it('shortens money', () => {
		expect(compactAed(12_400_000)).toBe('AED 12.4M')
		expect(compactAed(2_000_000)).toBe('AED 2M')
		expect(compactAed(240_000)).toBe('AED 240K')
		expect(compactAed(9_500)).toBe('AED 9.5K')
	})

	it('totals sale and rent apart', () => {
		const rows = [
			lead({ fields: { budget_aed: 2_000_000 } }),
			lead({ fields: { budget_aed: 1_500_000 } }),
			lead({ lead_type: 'tenant', deal_type: 'rent', fields: { budget_aed: 120_000 } }),
			lead()
		]
		expect(columnTotal(rows)).toBe('AED 3.5M · AED 120K/yr')
		expect(columnTotal([lead()])).toBe('')
	})

	it('drops only where the lead can go', () => {
		expect(canDrop(lead(), 'offer')).toBe(true)
		expect(canDrop(lead(), 'qualified')).toBe(false) // own column
		expect(canDrop(lead(), 'listed')).toBe(false) // seller/landlord stage
		expect(canDrop(lead({ lead_type: 'seller' }), 'viewing')).toBe(false)
		expect(canDrop(lead({ gated: true }), 'contacted')).toBe(false)
		expect(canDrop(lead({ gated: true }), 'lost')).toBe(true)
		expect(canDrop(lead({ id: 0 }), 'lost')).toBe(false) // unopened Vitevue lease
	})

	it('builds initials and the need line', () => {
		expect(initials('ALEXANDRU ION TIRIAC')).toBe('AT')
		expect(initials('Ashwin')).toBe('A')
		expect(
			needLine(
				lead({ fields: { budget_aed: 2_000_000 }, summary: { line: '2BR in Marina', sub: '' } })
			)
		).toBe('AED 2M · 2BR in Marina')
		expect(needLine(lead())).toBe('')
	})
})
