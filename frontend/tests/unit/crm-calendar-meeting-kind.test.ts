import { describe, expect, it } from 'vitest'
import type { EventKind } from '../../src/lib/crm/api/types'
import { EVENT_KIND_ORDER, EVENT_KINDS } from '../../src/lib/crm/config'

// The calendar edit form's "Event type" select lists EVENT_KIND_ORDER, labelled by EVENT_KINDS,
// and is bound to the event's stored kind. A meeting reopened from the server must find its
// own option there, or the form would show another type and could save it back.
describe('a meeting reopens in the calendar form as a Meeting', () => {
	it('offers Meeting as an event type, with its own label and colour', () => {
		const stored: EventKind = 'meeting'
		expect(EVENT_KIND_ORDER).toContain(stored)
		expect(EVENT_KINDS[stored].label).toBe('Meeting')
		expect(EVENT_KINDS[stored].color).toBe('var(--e-meet)')
	})

	it('keeps every kind the server can return selectable exactly once', () => {
		const kinds: EventKind[] = ['viewing', 'call', 'meeting', 'follow_up', 'deal_date', 'deadline']
		expect([...EVENT_KIND_ORDER].sort()).toEqual([...kinds].sort())
		for (const kind of kinds) expect(EVENT_KINDS[kind]).toBeDefined()
	})
})
