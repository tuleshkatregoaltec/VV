import { describe, expect, it } from 'vitest'
import type { CalendarEvent } from '$lib/crm/api/types'
import {
	calendarDays,
	calendarScope,
	eventColor,
	eventsOn,
	googleReturn,
	hasShared,
	homeCalendar,
	ownerInitials,
	ownerLabel,
	people,
	showFilter,
	viewHeading,
	viewOptions
} from '$lib/crm/calendar'
import { EVENT_KINDS } from '$lib/crm/config'

const event = (data: Partial<CalendarEvent>) =>
	({
		id: 7,
		date: '2026-11-17',
		end_date: '2026-11-17',
		time: '09:00',
		rescheduled_from: [],
		can_edit: true,
		redacted: false,
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

	it("leaves colleagues' events out of Home: its counters are the signed-in person's own", () => {
		const colleague = event({
			id: 9,
			kind: 'viewing',
			date: '2026-11-18',
			end_date: '2026-11-18',
			time: '08:30',
			can_edit: false
		})
		const mine = homeCalendar(events, week, '2026-11-18', '2026-11-18', '2026-11-18 08:00')
		const h = homeCalendar(
			[...events, colleague],
			week,
			'2026-11-18',
			'2026-11-18',
			'2026-11-18 08:00'
		)
		expect(h).toEqual(mine)
	})

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

describe('shared calendar labels', () => {
	it("marks a colleague's event with their initials so the title still fits a month cell", () => {
		expect(ownerInitials(event({}))).toBeNull()
		expect(ownerInitials(event({ can_edit: false, agent: 'Local Engineer' }))).toBe('LE')
		expect(ownerInitials(event({ can_edit: false, agent: 'Manager 2' }))).toBe('M2')
		expect(ownerInitials(event({ can_edit: false, agent: 'aisha' }))).toBe('A')
	})

	it("greys a colleague's private busy block instead of showing its kind", () => {
		expect(eventColor(event({ redacted: true, kind: 'viewing' }))).toBe('var(--line-2)')
		expect(eventColor(event({ kind: 'viewing' }))).toBe(EVENT_KINDS.viewing.color)
	})

	it("knows when the list holds colleagues' events", () => {
		expect(hasShared([event({}), event({ id: 8 })])).toBe(false)
		expect(hasShared([event({}), event({ id: 8, can_edit: false })])).toBe(true)
	})
})

describe('whose event it is', () => {
	const mine = event({ id: 1, owner_id: 'me', agent: 'You', owner_role: 'Manager' })
	const aisha = event({
		id: 2,
		owner_id: 'a1',
		agent: 'Aisha K',
		owner_role: 'Agent',
		can_edit: false
	})
	const omar = event({
		id: 3,
		owner_id: 'o1',
		agent: 'Omar B',
		owner_role: 'Agent',
		can_edit: false
	})

	it('labels your own events "You" and a colleague\'s with their name and role', () => {
		expect(ownerLabel(mine)).toBe('You')
		expect(ownerLabel(aisha)).toBe('Aisha K · Agent')
		expect(ownerLabel(event({ can_edit: false, agent: 'Former member', owner_role: null }))).toBe(
			'Former member'
		)
	})

	it('lists the people on screen once each, you first then by name', () => {
		expect(
			people([omar, aisha, mine, event({ ...aisha, id: 4 })]).map((p) => [p.id, p.label, p.you])
		).toEqual([
			['me', 'You', true],
			['a1', 'Aisha K · Agent', false],
			['o1', 'Omar B · Agent', false]
		])
	})
})

const team = (id: string, name: string, supervised: boolean, members: string[]) => ({
	id,
	name,
	supervised,
	members: members.map((user_id) => ({ user_id, name: NAMES[user_id] ?? user_id }))
})
const NAMES: Record<string, string> = { me: 'Manager Demo', a1: 'Aisha K', o1: 'Omar B', z: 'Zed' }
const everyone = Object.entries(NAMES).map(([user_id, name]) => ({ user_id, name }))
const ORG = {
	capabilities: { organization_admin: true },
	teams: [
		team('t1', 'Marina Team', false, ['me', 'a1']),
		team('t2', 'Downtown Team', false, ['o1'])
	],
	people: everyone
}
const MANAGER = {
	capabilities: { organization_admin: false },
	teams: [team('t1', 'Marina Team', true, ['me', 'a1'])],
	people: everyone
}

describe('what this calendar shows', () => {
	it('describes an owner or admin view as organization-wide', () => {
		const s = calendarScope(ORG)
		expect([s.kind, s.pill]).toEqual(['org', 'Organization-wide'])
		expect(s.description).toBe('All organization events, including managers and agents.')
		expect(s.people.map((p) => p.id)).toEqual(['me', 'a1', 'o1', 'z'])
		expect(s.rules).toHaveLength(3)
	})

	it("describes a manager's view by the teams they supervise, and lists only those members", () => {
		const s = calendarScope(MANAGER)
		expect([s.kind, s.pill]).toEqual(['team', 'Marina Team'])
		expect(s.description).toBe('Your events and events for members of Marina Team.')
		expect(s.people.map((p) => p.id)).toEqual(['me', 'a1'])
	})

	it("describes an agent's view as their own calendar, also while the scope is loading", () => {
		for (const scope of [
			undefined,
			{ capabilities: { organization_admin: false }, teams: [], people: [] }
		]) {
			const s = calendarScope(scope)
			expect([s.kind, s.pill]).toEqual(['own', 'Personal calendar'])
			expect(s.description).toBe('Only your own calendar events are shown.')
			expect(s.people).toEqual([])
		}
	})
})

describe('the View calendar dropdown', () => {
	const mine = event({ id: 1, owner_id: 'me', agent: 'You' })
	const aisha = event({
		id: 2,
		owner_id: 'a1',
		agent: 'Aisha K',
		owner_role: 'Agent',
		can_edit: false
	})
	const omar = event({
		id: 3,
		owner_id: 'o1',
		agent: 'Omar B',
		owner_role: 'Agent',
		can_edit: false
	})

	it('lists the whole organization, then each colleague, for an owner', () => {
		expect(viewOptions(calendarScope(ORG), 'me', [aisha, omar])).toEqual([
			{ value: 'all', label: 'Entire organization' },
			{ value: 'person:a1', label: 'Aisha K · Agent' },
			{ value: 'person:o1', label: 'Omar B · Agent' },
			{ value: 'person:z', label: 'Zed' }
		])
	})

	it('lists the team, your own calendar, then each team member, for a manager', () => {
		expect(viewOptions(calendarScope(MANAGER), 'me', [mine, aisha])).toEqual([
			{ value: 'all', label: 'Marina Team · everyone' },
			{ value: 'person:me', label: 'My calendar · Manager Demo' },
			{ value: 'person:a1', label: 'Aisha K · Agent' }
		])
	})

	it('offers nothing to an agent', () => {
		expect(viewOptions(calendarScope(undefined), 'me', [mine])).toEqual([])
	})

	it('narrows to the chosen calendar, never adding anyone', () => {
		const all = [mine, aisha, omar]
		const ids = (choice: string) => showFilter(all, choice).map((e) => e.id)
		expect(ids('all')).toEqual([1, 2, 3])
		expect(ids('person:me')).toEqual([1])
		expect(ids('person:o1')).toEqual([3])
	})

	it('says whose calendar is showing once one person is picked', () => {
		const s = calendarScope(MANAGER)
		expect(viewHeading(s, 'all')).toEqual({ description: s.description, pill: 'Marina Team' })
		expect(viewHeading(s, 'person:a1')).toEqual({
			description: 'Showing Aisha K’s calendar. Your events and events for members of Marina Team.',
			pill: 'Aisha K · calendar'
		})
	})
})

describe('the selected day', () => {
	it("lists the day's events, all-day first then by time, including multi-day ones", () => {
		const evs = [
			event({ id: 1, date: '2026-11-19', end_date: '2026-11-19', time: '16:00' }),
			event({ id: 2, date: '2026-11-18', end_date: '2026-11-20', time: null }),
			event({ id: 3, date: '2026-11-19', end_date: '2026-11-19', time: '09:00' }),
			event({ id: 4, date: '2026-11-21', end_date: '2026-11-21', time: '09:00' })
		]
		expect(eventsOn(evs, '2026-11-19').map((e) => e.id)).toEqual([2, 3, 1])
	})
})
