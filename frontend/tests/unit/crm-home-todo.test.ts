import { describe, expect, it } from 'vitest'
import type { InboundEnquiryResponse } from '$lib/api/generated/hey-api/types.gen'
import type { LeadRow } from '$lib/crm/api/types'
import { leadTodo, type TodoLead } from '$lib/crm/homeTodo'

const TODAY = '2026-11-18'

function lead(
	id: number,
	e: Partial<InboundEnquiryResponse> = {},
	row: Partial<LeadRow> = {}
): TodoLead {
	return {
		e: {
			sla_state: 'responded',
			next_follow_up: null,
			contact: {
				id,
				full_name: `L${id}`,
				phone: '+971500000000',
				consent_status: 'provided',
				do_not_contact: false
			},
			criteria: { budget_max_aed: 2_000_000, locations: ['JVC'] },
			...e
		} as InboundEnquiryResponse,
		row: {
			id,
			name: `Lead ${id}`,
			lead_type: 'buyer',
			stage: 'contacted',
			source: 'inbound',
			source_short: 'Bayut',
			gated: false,
			score: 50,
			area: 'JVC',
			...row
		} as LeadRow
	}
}

describe('Home › Gaps', () => {
	it('lists the most urgent gap per open lead, most urgent first', () => {
		const { gaps } = leadTodo(
			[
				lead(1),
				lead(2, { criteria: {} }, { area: '' }),
				lead(3, { next_follow_up: '2026-11-10' }),
				lead(4, { sla_state: 'overdue', next_follow_up: '2026-11-01' }),
				lead(5, { contact: { id: 5, full_name: 'x', consent_status: 'u', do_not_contact: false } }),
				lead(6, {}, { gated: true, source: 'file' })
			],
			TODAY
		)
		expect(gaps.map((g) => [g.ref_id, g.text])).toEqual([
			['4', 'First reply overdue'],
			['3', 'Follow-up overdue since 10 Nov'],
			['6', 'No prior deal on record · add a record before contacting'],
			['5', 'No phone or email'],
			['2', 'Budget and area missing']
		])
		expect(gaps[0]).toMatchObject({ ref_type: 'lead', detail: 'Lead 4 · Bayut' })
	})

	it('ignores won and lost leads, a follow-up due today, and sellers without a budget', () => {
		const { gaps } = leadTodo(
			[
				lead(1, { sla_state: 'overdue' }, { stage: 'won' }),
				lead(2, { sla_state: 'overdue' }, { stage: 'lost' }),
				lead(3, { next_follow_up: TODAY }),
				lead(4, { criteria: {} }, { lead_type: 'seller', area: '' })
			],
			TODAY
		)
		expect(gaps).toEqual([])
	})
})

describe('Home › Owner file', () => {
	it('shows owner-file leads at New or Contacted, best score first', () => {
		const { file_leads } = leadTodo(
			[
				lead(1, {}, { source: 'file', stage: 'new', score: 40 }),
				lead(2, {}, { source: 'file', stage: 'contacted', score: 80 }),
				lead(3, {}, { source: 'file', stage: 'qualified' }),
				lead(4, {}, { source: 'inbound', stage: 'new' }),
				lead(5, {}, { source: 'file', stage: 'lost' })
			],
			TODAY
		)
		expect(file_leads.map((l) => l.id)).toEqual([2, 1])
	})
})
