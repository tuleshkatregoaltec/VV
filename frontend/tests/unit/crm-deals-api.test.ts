import { afterEach, describe, expect, it, vi } from 'vitest'
import { client } from '$lib/api/client'
import type { DealResponse } from '$lib/api/generated/hey-api/types.gen'
import * as backend from '$lib/crm/api/backend'

afterEach(() => vi.restoreAllMocks())

const ME = { id: 'omar', first_name: 'Omar', last_name: 'Khan', email: 'o@x.ae' }

function deal(over: Partial<DealResponse> = {}): DealResponse {
	return {
		id: 12,
		reference: 'D-12',
		deal_type: 'sale',
		unit: 'JVC · Apartment',
		client: 'Sara Khan',
		counterparty: '',
		value_aed: 1_500_000,
		due_date: '2026-12-01',
		listing_id: null,
		lead_id: 7,
		agent_user_id: 'lina',
		team_id: 'north',
		origin: 'portal',
		origin_label: 'Portal',
		origin_source: 'Bayut',
		stages: [
			'Offer accepted',
			'Form F signed',
			'Mortgage / bank',
			'NOC',
			'Transfer booked',
			'Transferred'
		],
		stage_index: 1,
		stage: 'Form F signed',
		next_stage: 'Mortgage / bank',
		status: 'open',
		dld_transaction_id: null,
		created_at: '2026-11-18T08:00:00Z',
		updated_at: '2026-11-18T08:00:00Z',
		closed_at: null,
		...over
	} as DealResponse
}

function serve(routes: Record<string, unknown>) {
	return vi.spyOn(client, 'get').mockImplementation(async (url: string) => {
		const path = url.split('?')[0]
		if (path === '/api/v1/auth/me') return ME
		if (path === '/api/v1/crm/assignment/scope')
			return { people: [{ user_id: 'lina', name: 'Lina Haddad' }] }
		if (path in routes) return routes[path]
		throw new Error(`unexpected GET ${url}`)
	})
}

describe('deals from the backend', () => {
	it('lists deals with the agent named, the origin and the next step', async () => {
		const get = serve({
			'/api/v1/crm/deals': {
				items: [deal()],
				counts: { open: 1, closed: 0, lost: 0, missing_documents: 0, sale: 1, rent: 0 },
				open_value_aed: 1_500_000
			}
		})
		const list = await backend.listDeals('pipeline', 'sale')
		expect(get).toHaveBeenCalledWith('/api/v1/crm/deals?tab=pipeline&deal_type=sale')
		const [row] = list.items
		expect(row).toMatchObject({
			id: 'D-12',
			agent: 'Lina Haddad',
			origin: 'Portal',
			stage: 'Form F signed',
			next_step: 'Next: Mortgage / bank',
			closed: false,
			approval: 'none'
		})
		expect(list.counts.open).toBe(1)
		expect(list.open_value_aed).toBe(1_500_000)
	})

	it("shows the conveyancing checklist from the deal's stage", async () => {
		serve({ '/api/v1/crm/deals/12': deal() })
		const d = await backend.getDeal('D-12')
		expect(d.checklist.map((c) => c.state)).toEqual(['done', 'now', 'next', 'next', 'next', 'next'])
		expect(d.lead).toEqual({ id: '7', label: 'Sara Khan' })
	})

	it('moves with the stage the screen showed, so a stale move is refused', async () => {
		serve({})
		const post = vi.spyOn(client, 'post').mockResolvedValue(deal({ stage_index: 2 }))
		const r = await backend.moveDeal('D-12', 'next', 1)
		expect(post).toHaveBeenCalledWith('/api/v1/crm/deals/12/move', {
			direction: 'next',
			expected_stage_index: 1
		})
		expect(r.data.id).toBe('D-12')
	})

	it('names a won deal as completed and dates it by its close', async () => {
		serve({
			'/api/v1/crm/deals/12': deal({
				status: 'won',
				next_stage: null,
				closed_at: '2026-11-20T10:00:00Z'
			})
		})
		const d = await backend.getDeal('D-12')
		expect(d.closed).toBe(true)
		expect(d.next_step).toBe('Completed')
		expect(d.due_date).toBe('2026-11-20')
		expect(d.checklist.every((c) => c.state === 'done')).toBe(true)
	})
})
