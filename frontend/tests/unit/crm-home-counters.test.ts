import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, client } from '$lib/api/client'
import * as backend from '$lib/crm/api/backend'

afterEach(() => vi.restoreAllMocks())

const area = (name: string, psf: number | null) => ({
	area_name: name,
	avg_sale_price_sqft_12m: psf,
	median_annual_rent: 89999.4,
	gross_yield_pct: 4.1000477
})

describe('Home › Market', () => {
	it("reads one area's 12-month figures, rounded for the card", async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue(area('Business Bay', 2681.89))
		expect(await backend.areaMarket('Business Bay')).toEqual({
			area: 'Business Bay',
			psf_aed: 2682,
			rent_median_aed: 89999,
			yield_pct: 4.1
		})
		expect(get).toHaveBeenCalledWith('/api/v1/areas/Business%20Bay')
	})

	it('is empty for an area the market data does not know or without sales', async () => {
		vi.spyOn(client, 'get').mockRejectedValueOnce(new ApiError('Area not found', 404, 'not_found'))
		expect(await backend.areaMarket('Dubai Marina')).toBeNull()
		vi.spyOn(client, 'get').mockResolvedValueOnce(area('Al Aweer', null))
		expect(await backend.areaMarket('Al Aweer')).toBeNull()
	})
})

describe('Home counters', () => {
	async function homeWith(routes: (url: string) => unknown) {
		vi.spyOn(backend, 'listLeads').mockResolvedValue({
			items: [],
			total: 0,
			new_count: 0
		} as unknown as Awaited<ReturnType<typeof backend.listLeads>>)
		vi.spyOn(backend, 'listCalendarEvents').mockResolvedValue([])
		vi.spyOn(backend, 'homeTodo').mockResolvedValue({ gaps: [], file_leads: [] })
		vi.spyOn(backend, 'listDeals').mockResolvedValue({
			items: [],
			counts: { open: 0, missing_documents: 0, closed: 0, sale: 0, rent: 0 },
			open_value_aed: 0,
			totals: { gross: 0, agent: 0, agency: 0 }
		})
		vi.spyOn(client, 'get').mockImplementation(async (url: string) => routes(url))
		const { crm } = await import('$lib/crm/api')
		return crm.home('2026-11-18')
	}

	it("uses the first of the agent's areas that has figures", async () => {
		const h = await homeWith((url) => {
			if (url.endsWith('/area-preferences'))
				return {
					areas: ['Dubai Marina', 'Business Bay', 'JVC'],
					forward_days: 60,
					lookback_days: 30
				}
			if (url.endsWith('/Dubai%20Marina')) throw new ApiError('Area not found', 404, 'not_found')
			if (url.endsWith('/Business%20Bay')) return area('Business Bay', 2681.89)
			throw new Error(`unexpected ${url}`)
		})
		expect(h.counters.market?.area).toBe('Business Bay')
	})

	it('asks for an area when none are saved, and never invents listings or commission', async () => {
		const h = await homeWith((url) => {
			if (url.endsWith('/area-preferences')) return { areas: [] }
			throw new Error(`unexpected ${url}`)
		})
		expect(h.counters.market).toBeNull()
		expect(h.counters.expiring_14).toBeNull()
		expect(h.counters.commission).toBeNull()
	})

	it('still renders Home when the market data is unavailable', async () => {
		const h = await homeWith((url) => {
			if (url.endsWith('/area-preferences')) return { areas: ['Business Bay'] }
			throw new ApiError('Service unavailable', 503, 'unavailable')
		})
		expect(h.counters.market).toBeNull()
		expect(h.date).toBe('2026-11-18')
	})
})

describe('Home › Conveyancing', () => {
	it('shows the open deals and counts them', async () => {
		vi.spyOn(backend, 'listLeads').mockResolvedValue({
			items: [],
			total: 0,
			new_count: 0
		} as unknown as Awaited<ReturnType<typeof backend.listLeads>>)
		vi.spyOn(backend, 'listCalendarEvents').mockResolvedValue([])
		vi.spyOn(backend, 'homeTodo').mockResolvedValue({ gaps: [], file_leads: [] })
		vi.spyOn(backend, 'getFeedPreferences').mockResolvedValue({
			areas: [],
			forward_days: 60,
			lookback_days: 30
		})
		const deal = { id: 'D-1', deal_type: 'sale', stage_index: 1, value_aed: 1_850_000 }
		const list = vi.spyOn(backend, 'listDeals').mockResolvedValue({
			items: [deal],
			counts: { open: 1, missing_documents: 0, closed: 0, sale: 1, rent: 0 },
			open_value_aed: 1_850_000,
			totals: { gross: 0, agent: 0, agency: 0 }
		} as unknown as Awaited<ReturnType<typeof backend.listDeals>>)
		const { crm } = await import('$lib/crm/api')
		const h = await crm.home('2026-11-18')
		expect(list).toHaveBeenCalledWith('conveyancing')
		expect(h.conveyancing.map((d) => d.id)).toEqual(['D-1'])
		expect(h.facts.conveyancing).toBe(1)
		expect(h.counters.conveyancing).toEqual({ count: 1, value_aed: 1_850_000 })
	})
})
