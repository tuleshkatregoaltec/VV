import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, client } from '$lib/api/client'
import * as backend from '$lib/crm/api/backend'

afterEach(() => vi.restoreAllMocks())

describe('Google Calendar sign-in', () => {
	it('finishes sign-in by posting what Google returned, as the signed-in user', async () => {
		const post = vi
			.spyOn(client, 'post')
			.mockResolvedValue({ configured: true, connected: true, email: 'a@x.ae' })
		const status = await backend.completeGoogleCalendar('4/abc', 'xyz')
		expect(post).toHaveBeenCalledWith('/api/v1/crm/calendar/google/complete', {
			code: '4/abc',
			state: 'xyz'
		})
		expect(status.connected).toBe(true)
	})
})

describe('calendar events', () => {
	it('lists the visible range', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue([])
		await backend.listCalendarEvents('2026-11-01', '2026-12-12')
		expect(get).toHaveBeenCalledWith('/api/v1/crm/calendar/events?start=2026-11-01&end=2026-12-12')
	})

	it("books a viewing on the lead's calendar endpoint", async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({ id: 1 })
		const body = { date: '2026-11-20', time: '10:00', listing_id: null, note: '' }
		await backend.bookCalendarViewing(7, body)
		expect(post).toHaveBeenCalledWith('/api/v1/crm/calendar/viewings/7', body)
	})

	it('reschedules with date and time only', async () => {
		const patch = vi.spyOn(client, 'patch').mockResolvedValue({ id: 3 })
		await backend.moveCalendarEvent(3, '2026-11-21', null)
		expect(patch).toHaveBeenCalledWith('/api/v1/crm/calendar/events/3', {
			date: '2026-11-21',
			time: null
		})
	})

	it('treats an event that is already gone as deleted', async () => {
		const { crm } = await import('$lib/crm/api')
		vi.spyOn(client, 'delete').mockRejectedValue(new ApiError('gone', 404, 'not_found'))
		await expect(crm.events.remove(9)).resolves.toEqual({
			data: { deleted: '9' },
			undo_token: null
		})
	})

	it('still reports any other delete failure', async () => {
		const { crm } = await import('$lib/crm/api')
		vi.spyOn(client, 'delete').mockRejectedValue(new ApiError('Google down', 502, 'bad_gateway'))
		await expect(crm.events.remove(9)).rejects.toThrow('Google down')
	})
})

describe('email', () => {
	it('asks for the leads with search, type, source and ids', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ items: [], total: 0, sources: [] })
		await backend.emailLeads({ search: ' sara ', intent: 'buy', source: 'Bayut', ids: [1, 2] })
		expect(get).toHaveBeenCalledWith(
			'/api/v1/crm/email/leads?search=sara&intent=buy&source=Bayut&ids=1&ids=2'
		)
	})

	it('filters tracking by status only when one is chosen', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ items: [], counts: {} })
		await backend.emailSends()
		await backend.emailSends('bounced')
		expect(get.mock.calls.map((c) => c[0])).toEqual([
			'/api/v1/crm/email/sends',
			'/api/v1/crm/email/sends?status=bounced'
		])
	})

	it("reads one lead's thread", async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue([])
		await backend.emailThread(7)
		expect(get).toHaveBeenCalledWith('/api/v1/crm/email/leads/7/thread')
	})
})
