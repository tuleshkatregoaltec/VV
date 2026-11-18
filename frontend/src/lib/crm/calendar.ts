import type { CalendarEvent, EventKind } from './api/types'
import { addDays, dayLabel } from './format'

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

/** Whether an event covers a day (a multi-day event covers every day it spans). */
const covers = (e: CalendarEvent, day: string) => e.date <= day && (e.end_date || e.date) >= day

/** All-day first, then by start time. */
const byTime = (a: CalendarEvent, b: CalendarEvent) =>
	(a.time ?? '').localeCompare(b.time ?? '') || a.id - b.id

/**
 * Home's calendar parts from the same events the Calendar page shows: the week strip's dots, the
 * selected day's list, its count, and this week's viewings with the next one still to come.
 * `now` is "YYYY-MM-DD HH:MM" on this device.
 */
export function homeCalendar(
	events: CalendarEvent[],
	week: string[],
	selected: string,
	today: string,
	now: string
) {
	const day = events.filter((e) => covers(e, selected)).sort(byTime)
	const viewings = events
		.filter((e) => e.kind === 'viewing' && week.some((d) => covers(e, d)))
		.sort((a, b) => a.date.localeCompare(b.date) || byTime(a, b))
	const next = viewings.find((e) => e.outcome !== 'Done' && `${e.date} ${e.time ?? '23:59'}` >= now)
	const when = next ? (next.date === today ? 'Today' : dayLabel(next.date)) : null
	return {
		week: week.map((date) => ({
			date,
			kinds: events
				.filter((e) => covers(e, date))
				.sort(byTime)
				.map((e): EventKind => e.kind)
		})),
		day,
		events_today: day.length,
		viewings_week: {
			count: viewings.length,
			next: next ? (next.time ? `${when} · ${next.time}` : `${when} · all day`) : null
		}
	}
}
