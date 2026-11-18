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

/** What Google handed back after sign-in, read from the calendar page's URL fragment. */
export type GoogleReturn = { code: string; state: string } | { error: true } | null

/**
 * The backend's callback forwards Google's one-time code and state in the fragment (never sent
 * to a server). The signed-in page posts them to finish sign-in; the server only accepts a state
 * this same user started.
 */
export function googleReturn(hash: string): GoogleReturn {
	const params = new URLSearchParams(hash.startsWith('#') ? hash.slice(1) : hash)
	if (params.get('google_calendar') === 'error') return { error: true }
	const code = params.get('google_code')
	const state = params.get('google_state')
	return code && state ? { code, state } : null
}
