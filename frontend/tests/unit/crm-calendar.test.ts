import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '$lib/crm/api/types'
import { calendarDays, googleReturn, homeCalendar } from '$lib/crm/calendar'

const event = (data: Partial<CalendarEvent>) =>
	({
		id: 7,
		date: '2026-11-17',
		end_date: '2026-11-17',
		time: '09:00',
		rescheduled_from: [],
		...data
	}) as CalendarEvent

describe('calendar occupied days', () => {
	it('shows every occupied day, including an event that starts before the visible range', () => {
		const days = calendarDays(
			[event({ date: '2026-11-15', end_date: '2026-11-20' })],
			'2026-11-17',
			'2026-11-19'
		)
		expect([...days.keys()]).toEqual(['2026-11-17', '2026-11-18', '2026-11-19'])
		expect([...days.values()].every((items) => items.length === 1 && !items[0].moved)).toBe(true)
	})

	it('shows a repeated old slot only once even when every recurrence carries its history', () => {
		const old = { date: '2026-11-16', time: '09:00' }
		const history = [old, { date: '2026-11-18', time: '10:00' }, old]
		const days = calendarDays(
			[
				event({ rescheduled_from: history }),
				event({ date: '2026-11-24', end_date: '2026-11-24', rescheduled_from: history })
			],
			'2026-11-01',
			'2026-11-30'
		)
		expect(days.get(old.date)).toHaveLength(1)
		expect(days.get('2026-11-18')).toHaveLength(1)
		expect(days.get('2026-11-24')).toHaveLength(1)
	})
})

describe('back from Google sign-in', () => {
	it('reads the one-time code and state from the fragment', () => {
		expect(googleReturn('#google_code=4%2Fabc&google_state=xyz')).toEqual({
			code: '4/abc',
			state: 'xyz'
		})
	})

	it('reports a cancelled or failed sign-in', () => {
		expect(googleReturn('#google_calendar=error')).toEqual({ error: true })
	})

	it('ignores anything else, including half a return', () => {
		expect(googleReturn('')).toBeNull()
		expect(googleReturn('#google_code=abc')).toBeNull()
		expect(googleReturn('#section')).toBeNull()
	})
})

describe('Home calendar', () => {
	const week = [
		'2026-11-16',
		'2026-11-17',
		'2026-11-18',
		'2026-11-19',
		'2026-11-20',
		'2026-11-21',
		'2026-11-22'
	]
	const events = [
		event({ id: 1, kind: 'viewing', date: '2026-11-18', end_date: '2026-11-18', time: '15:00' }),
		event({ id: 2, kind: 'call', date: '2026-11-18', end_date: '2026-11-18', time: '09:30' }),
		event({ id: 3, kind: 'viewing', date: '2026-11-16', end_date: '2026-11-16', time: '11:00' }),
		event({ id: 4, kind: 'follow_up', date: '2026-11-17', end_date: '2026-11-19', time: null }),
		event({
			id: 5,
			kind: 'viewing',
			date: '2026-11-20',
			end_date: '2026-11-20',
			time: '10:00',
			outcome: 'Done'
		}),
		event({ id: 6, kind: 'viewing', date: '2026-11-21', end_date: '2026-11-21', time: '12:00' })
	]

	it("lists the selected day's events, all-day first then by time, and counts them", () => {
		const h = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-18 08:00')
		expect(h.day.map((e) => e.id)).toEqual([4, 2, 1])
		expect(h.events_today).toBe(3)
	})

	it('puts a dot on every day an event covers, including each day of a multi-day one', () => {
		const h = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-18 08:00')
		expect(h.week.map((d) => d.kinds.length)).toEqual([1, 1, 3, 1, 1, 1, 0])
		expect(h.week[2].kinds).toEqual(['follow_up', 'call', 'viewing'])
	})

	it("counts the week's viewings and names the next one still to come", () => {
		const today = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-18 08:00')
		expect(today.viewings_week).toEqual({ count: 4, next: 'Today · 15:00' })
		// After 15:00 the next is Saturday's (Friday's is already done).
		const later = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-18 16:00')
		expect(later.viewings_week.next).toBe('Sat 21 Nov · 12:00')
		const none = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-23 00:00')
		expect(none.viewings_week.next).toBeNull()
	})

	it('is empty without events', () => {
		const h = homeCalendar([], week, '2026-11-18', '2026-11-18', '2026-11-18 08:00')
		expect(h.day).toEqual([])
		expect(h.viewings_week).toEqual({ count: 0, next: null })
		expect(h.week.every((d) => d.kinds.length === 0)).toBe(true)
	})
})
