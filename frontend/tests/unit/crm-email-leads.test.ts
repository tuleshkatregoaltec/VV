import { describe, expect, it } from 'vitest'
import { fillTokens, messageParts, suits, typesLabel } from '$lib/crm/email'

describe('fillTokens', () => {
	it('matches the backend: lead tokens fill, anything else stays visible', () => {
		// Leads have no company, so {{company}} must show in the preview instead of vanishing.
		const out = fillTokens('Hi {{first_name}} ({{ email }}) at {{company}}', {
			name: 'Sara Khan',
			email: 's@x.ae'
		})
		expect(out).toBe('Hi Sara (s@x.ae) at {{company}}')
	})
})

describe('templates by lead type', () => {
	it('a template with no types suits every lead', () => {
		expect(suits([], ['let'])).toBe(true)
		expect(typesLabel([])).toBe('All types')
	})

	it('a typed template is suggested only when a chosen lead has one of its types', () => {
		// "Thinking of selling?" is for sellers and untyped owners, never for tenants.
		expect(suits(['sell', 'unknown'], ['rent'])).toBe(false)
		expect(suits(['sell', 'unknown'], ['rent', 'unknown'])).toBe(true)
	})

	it('names types in the Leads page order, whatever order they were ticked in', () => {
		expect(typesLabel(['sell', 'buy'])).toBe('Buyer, Seller')
	})
})

describe('messageParts (matches the email the backend sends)', () => {
	it('reads a button, a named link and a bare link', () => {
		const [p1, p2] = messageParts(
			'See [the shortlist](https://vv.ae/s) or https://vv.ae/x.\n\n[button: Book a viewing](https://vv.ae/book)'
		)
		expect(p1).toEqual([
			{ kind: 'text', text: 'See ' },
			{ kind: 'link', text: 'the shortlist', url: 'https://vv.ae/s' },
			{ kind: 'text', text: ' or ' },
			{ kind: 'link', text: 'https://vv.ae/x', url: 'https://vv.ae/x' },
			{ kind: 'text', text: '.' }
		])
		expect(p2).toEqual([{ kind: 'button', text: 'Book a viewing', url: 'https://vv.ae/book' }])
	})

	it('never makes a non-web target clickable', () => {
		expect(messageParts('[x](javascript:alert(1))')[0].every((p) => p.kind === 'text')).toBe(true)
	})
})
