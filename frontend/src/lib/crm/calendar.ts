import type { CalendarEvent, EventKind } from './api/types'
import { EVENT_KINDS } from './config'
import { addDays, dayLabel } from './format'

/** A colleague's initials for the month grid ("Local Engineer" → "LE"); null for your own. */
export const ownerInitials = (e: CalendarEvent) =>
	e.can_edit
		? null
		: e.agent
				.split(/\s+/)
				.filter(Boolean)
				.slice(0, 2)
				.map((word) => word[0].toUpperCase())
				.join('')

/** Whose event it is: "You", or a colleague's name and role ("Aisha K · Agent"). */
export const ownerLabel = (e: CalendarEvent) =>
	e.can_edit
		? 'You'
		: e.owner_role && e.owner_role !== e.agent
			? `${e.agent} · ${e.owner_role}`
			: e.agent

const ownerKey = (e: CalendarEvent) => e.owner_id ?? e.agent

export type Person = { id: string; label: string; you: boolean }

/** The people whose events are on screen, once each: you first, then by name. */
export function people(events: CalendarEvent[]): Person[] {
	const first = new Map<string, CalendarEvent>()
	for (const e of events) if (!first.has(ownerKey(e))) first.set(ownerKey(e), e)
	return [...first.values()]
		.map((e) => ({ id: ownerKey(e), label: ownerLabel(e), you: e.can_edit }))
		.sort((a, b) => Number(b.you) - Number(a.you) || a.label.localeCompare(b.label))
}

/** The parts of the assignment scope this page reads (who may see whom comes from the server). */
export type ScopeInput = {
	capabilities: { organization_admin: boolean }
	teams: { id: string; name: string; supervised: boolean; members: { user_id: string }[] }[]
	people?: { user_id: string; name: string }[]
}

export type CalendarScope = {
	kind: 'org' | 'team' | 'own'
	pill: string
	description: string
	rules: [string, string][]
	teams: { id: string; name: string; members: string[] }[]
	/** Calendars this view can open, in the order the server lists them. */
	people: { id: string; name: string }[]
}

const EDIT_RULE: [string, string] = [
	'Editing',
	'You can edit your own events. Other people’s events are view only.'
]
const PRIVATE_RULE: [string, string] = [
	'Private events',
	'Other people’s private events show as Busy; details stay hidden.'
]

/** What this calendar shows the signed-in person, in words: their header line and access card. */
export function calendarScope(scope: ScopeInput | undefined): CalendarScope {
	const teams = (scope?.teams ?? []).map((t) => ({
		id: t.id,
		name: t.name,
		supervised: t.supervised,
		members: t.members.map((m) => m.user_id)
	}))
	const everyone = (scope?.people ?? []).map((p) => ({ id: p.user_id, name: p.name }))
	if (scope?.capabilities.organization_admin)
		return {
			kind: 'org',
			pill: 'Organization-wide',
			description: 'All organization events, including managers and agents.',
			rules: [
				[
					'Organization-wide',
					'See events for every organization member, including people outside teams.'
				],
				PRIVATE_RULE,
				EDIT_RULE
			],
			teams: teams.map(({ supervised: _, ...t }) => t),
			people: everyone
		}
	const supervised = teams.filter((t) => t.supervised).map(({ supervised: _, ...t }) => t)
	if (supervised.length) {
		const names = supervised.map((t) => t.name).join(', ')
		const members = new Set(supervised.flatMap((t) => t.members))
		return {
			kind: 'team',
			pill: names,
			description: `Your events and events for members of ${names}.`,
			rules: [
				['Your team', 'See your own events and events for people in the teams you supervise.'],
				EDIT_RULE
			],
			teams: supervised,
			people: everyone.filter((p) => members.has(p.id))
		}
	}
	return {
		kind: 'own',
		pill: 'Personal calendar',
		description: 'Only your own calendar events are shown.',
		rules: [
			['Your events', 'See events that belong to your account.'],
			['Team events', 'Your manager’s and teammates’ events stay private to them.'],
			['Editing', 'You can edit your own events.']
		],
		teams: [],
		people: []
	}
}

export type ViewOption = { value: string; label: string }

/**
 * The View calendar dropdown: only calendars this role can open. Owners: the whole organization,
 * then each colleague. Managers: their team(s), their own calendar, then each team member.
 */
export function viewOptions(
	scope: CalendarScope,
	myId: string,
	events: CalendarEvent[]
): ViewOption[] {
	if (scope.kind === 'own') return []
	const roles = new Map(events.map((e) => [ownerKey(e), e.owner_role]))
	const colleague = (p: { id: string; name: string }) => {
		const role = roles.get(p.id)
		return { value: `person:${p.id}`, label: role ? `${p.name} · ${role}` : p.name }
	}
	const others = scope.people.filter((p) => p.id !== myId).map(colleague)
	if (scope.kind === 'org') return [{ value: 'all', label: 'Entire organization' }, ...others]
	const myName = scope.people.find((p) => p.id === myId)?.name
	return [
		{ value: 'all', label: `${scope.pill} · everyone` },
		{ value: `person:${myId}`, label: myName ? `My calendar · ${myName}` : 'My calendar' },
		...others
	]
}

/** The events the chosen calendar keeps. It only narrows what the server sent. */
export function showFilter(events: CalendarEvent[], choice: string) {
	if (!choice.startsWith('person:')) return events
	const id = choice.slice('person:'.length)
	return events.filter((e) => ownerKey(e) === id)
}

/** The header line and access badge, naming the calendar once one person is picked. */
export function viewHeading(scope: CalendarScope, choice: string) {
	const id = choice.startsWith('person:') ? choice.slice('person:'.length) : null
	const name = id ? scope.people.find((p) => p.id === id)?.name : null
	return name
		? {
				description: `Showing ${name}’s calendar. ${scope.description}`,
				pill: `${name} · calendar`
			}
		: { description: scope.description, pill: scope.pill }
}

/** The first team (of those this view covers) a colleague belongs to, for "Name · Role · Team". */
export const ownerTeam = (scope: CalendarScope, e: CalendarEvent) =>
	e.can_edit ? null : (scope.teams.find((t) => t.members.includes(ownerKey(e)))?.name ?? null)

/** A colleague's private busy block is grey: its kind was not sent. */
export const eventColor = (e: CalendarEvent) =>
	e.redacted ? 'var(--line-2)' : EVENT_KINDS[e.kind].color

/** Whether the list holds colleagues' events (a manager's or owner's view). */
export const hasShared = (events: CalendarEvent[]) => events.some((e) => !e.can_edit)

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

/** One day's events: all-day first, then by start time (multi-day events on every day they cover). */
export const eventsOn = (events: CalendarEvent[], day: string) =>
	events.filter((e) => covers(e, day)).sort(byTime)

/**
 * Home's calendar parts from the same events the Calendar page shows: the week strip's dots, the
 * selected day's list, its count, and this week's viewings with the next one still to come.
 * `now` is "YYYY-MM-DD HH:MM" on this device.
 */
export function homeCalendar(
	all: CalendarEvent[],
	week: string[],
	selected: string,
	today: string,
	now: string
) {
	// Home's counters are the signed-in person's own; colleagues' events stay on the Calendar page.
	const events = all.filter((e) => e.can_edit)
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
