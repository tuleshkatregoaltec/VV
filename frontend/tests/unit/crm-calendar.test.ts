import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '$lib/crm/api/types'
import { calendarDays } from '$lib/crm/calendar'

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
