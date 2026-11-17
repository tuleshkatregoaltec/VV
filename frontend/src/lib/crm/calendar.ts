import type { CalendarEvent } from './api/types'
import { addDays } from './format'

export type DayItem = { event: CalendarEvent; time: string | null; moved: boolean; key: string }

/** Occupied days in the visible grid, with each earlier slot shown once per series. */
export function calendarDays(events: CalendarEvent[], first: string, last: string) {
	const days = new Map<string, DayItem[]>()
	const seen = new Set<string>()
	const add = (date: string, event: CalendarEvent, time: string | null, moved: boolean) => {
		const key = `${event.id}-${date}-${moved}-${time}`
		if (date < first || date > last || seen.has(key)) return
		seen.add(key)
		days.set(date, [...(days.get(date) ?? []), { event, time, moved, key }])
	}
	for (const event of events) {
		const end = event.end_date || event.date
		for (
			let day = event.date < first ? first : event.date;
			day <= end && day <= last;
			day = addDays(day, 1)
		) {
			add(day, event, event.time, false)
		}
		for (const slot of event.rescheduled_from ?? []) add(slot.date, event, slot.time, true)
	}
	for (const items of days.values()) items.sort((a, b) => Number(a.moved) - Number(b.moved))
	return days
}
