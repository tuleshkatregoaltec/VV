import { describe, expect, it } from 'vitest'

import { inboxToggleView } from '$lib/whatsapp/connect-state'

const row = { enabled: true, automation_active: true, automation_paused_reason: null }

describe('inboxToggleView (legacy "Automatic replies" switch in the inbox)', () => {
	it('says on only when replies are really running', () => {
		expect(inboxToggleView(row)).toEqual({ kind: 'on', text: 'Automatic replies on', note: null })
	})

	it('says off, and that sending is disabled, when the agent switched it off', () => {
		const view = inboxToggleView({ ...row, enabled: false, automation_active: false })
		expect(view.kind).toBe('off')
		expect(view.text).toBe('Automatic replies off')
		expect(view.note).toBe('Sending is disabled for this number, including approvals.')
	})

	it('says paused, with the reason, when the switch is on but the server paused replies', () => {
		const view = inboxToggleView({
			...row,
			automation_active: false,
			automation_paused_reason: 'assistant_disabled'
		})
		expect(view.kind).toBe('paused')
		expect(view.text).toBe('Automatic replies paused')
		expect(view.note).toBe(
			'Automatic replies are paused by Vitevue. New messages are not answered or added to the inbox here for now, so keep replying in WhatsApp yourself.'
		)
		expect(view.note).not.toMatch(/go to your inbox/)
	})

	it('says the number is disconnected, not paused by Vitevue, when the connection status is disconnected', () => {
		const view = inboxToggleView({
			...row,
			status: 'disconnected',
			automation_active: false,
			automation_paused_reason: null
		})
		expect(view.kind).toBe('disconnected')
		expect(view.text).toBe('Automatic replies not running')
		expect(view.note).toBe(
			'This number is disconnected, so automatic replies are not running. Reconnect it to start them again.'
		)
	})

	it('treats any status other than connected as not connected', () => {
		const view = inboxToggleView({ ...row, status: 'suspended', automation_active: false })
		expect(view.kind).toBe('disconnected')
		expect(view.note).not.toMatch(/Vitevue/)
	})

	it('reads a switched-on, inactive row with no pause reason as disconnected when the API omits status', () => {
		const view = inboxToggleView({
			enabled: true,
			automation_active: false,
			automation_paused_reason: null
		})
		expect(view.kind).toBe('disconnected')
	})

	it('keeps the generic Vitevue pause when the fields are missing on a connected number', () => {
		const view = inboxToggleView({ enabled: true, status: 'connected' })
		expect(view.kind).toBe('paused')
		expect(view.text).toBe('Automatic replies paused')
		expect(view.note).toBe('Automatic replies are paused by Vitevue.')
	})

	it('tells the agent to keep replying themselves when Vitevue is not reading messages', () => {
		const view = inboxToggleView({
			...row,
			automation_active: false,
			automation_paused_reason: 'intake_disabled'
		})
		expect(view.kind).toBe('paused')
		expect(view.note).toMatch(/not reading new WhatsApp messages/)
		expect(view.note).toMatch(/keep replying in WhatsApp yourself/)
	})
})
