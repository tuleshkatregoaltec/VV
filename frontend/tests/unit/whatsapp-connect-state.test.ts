import { describe, expect, it } from 'vitest'

import type { AgentConnectionStatus } from '$lib/api/whatsapp-connect'
import {
	automationView,
	contactsSyncPending,
	healthErrorText,
	sendingWarning,
	stepStates
} from '$lib/whatsapp/connect-state'

const base: AgentConnectionStatus = {
	state: 'connected',
	signup_configured: true,
	connection_id: 'c1',
	phone_number_id: 'p1',
	waba_id: 'w1',
	business_id: 'b1',
	display_phone_number: '+971 50 123 4567',
	display_name: 'Sara Properties',
	onboarding_type: 'whatsapp_business_app',
	automation_enabled: false,
	automation_active: false,
	automation_paused_reason: null,
	connected_at: '2026-11-06T09:00:00Z',
	disconnected_at: null,
	last_account_event: null,
	quality_rating: 'GREEN',
	can_send_message: 'AVAILABLE',
	health_errors: [],
	payment_method_status: 'unknown',
	contacts: { total: 0, blocked: 0, sync_requested_at: null, synced_at: null }
}

describe('stepStates', () => {
	it('starts at connect when nothing is connected', () => {
		expect(stepStates(null)).toEqual(['current', 'upcoming', 'upcoming'])
		expect(stepStates({ ...base, state: 'disconnected' })).toEqual([
			'current',
			'upcoming',
			'upcoming'
		])
	})

	it('moves to blocking once connected, then to turning replies on', () => {
		expect(stepStates(base)).toEqual(['done', 'current', 'upcoming'])
		const blocked = { ...base, contacts: { ...base.contacts, blocked: 3 } }
		expect(stepStates(blocked)).toEqual(['done', 'done', 'current'])
	})

	it('marks everything done when replies are on', () => {
		expect(stepStates({ ...base, automation_enabled: true })).toEqual(['done', 'done', 'done'])
	})
})

describe('contactsSyncPending', () => {
	it('is pending until the sync time is set', () => {
		expect(contactsSyncPending(base)).toBe(true)
		const synced = { ...base, contacts: { ...base.contacts, synced_at: '2026-11-06T09:05:00Z' } }
		expect(contactsSyncPending(synced)).toBe(false)
	})
})

describe('sendingWarning', () => {
	it('is silent when sending is available or unknown', () => {
		expect(sendingWarning('AVAILABLE')).toBeNull()
		expect(sendingWarning(null)).toBeNull()
	})
	it('explains limited and blocked in plain words', () => {
		expect(sendingWarning('LIMITED')).toMatchObject({ tone: 'amber' })
		expect(sendingWarning('BLOCKED')).toMatchObject({ tone: 'red' })
		expect(sendingWarning('BLOCKED')?.text).toMatch(/whatsapp manager/i)
	})
})

describe('healthErrorText', () => {
	it('reads Meta’s error shapes and plain strings', () => {
		expect(healthErrorText('Business not verified')).toBe('Business not verified')
		expect(healthErrorText({ error_description: 'Phone needs update' })).toBe('Phone needs update')
		expect(healthErrorText({ message: 'Something' })).toBe('Something')
		expect(healthErrorText({ nope: 1 })).toBe('Meta reported a problem with this number.')
	})
})

describe('automationView', () => {
	it('is off when the agent has not switched replies on', () => {
		expect(automationView(base)).toMatchObject({ kind: 'off', label: 'Off', note: null })
	})

	it('is on only when replies are actually running', () => {
		const on = { ...base, automation_enabled: true, automation_active: true }
		expect(automationView(on)).toMatchObject({ kind: 'on', label: 'On', note: null })
	})

	it('is paused, with the reason in plain words, when the switch is on but the server has replies off', () => {
		const paused = {
			...base,
			automation_enabled: true,
			automation_paused_reason: 'assistant_disabled' as const
		}
		const view = automationView(paused)
		expect(view.kind).toBe('paused')
		expect(view.label).toBe('Paused')
		expect(view.note).toBe(
			'Automatic replies are paused by Vitevue. New messages are not answered or added to the inbox here for now, so keep replying in WhatsApp yourself.'
		)
		expect(view.note).not.toMatch(/go to your inbox/)
		expect(view.resumeNote).toBe(
			'Your switch stays on, so replies start again by themselves when Vitevue resumes them.'
		)
	})

	it('blames the disconnected number, not Vitevue, and never promises replies resume by themselves', () => {
		const view = automationView(
			{ ...base, automation_enabled: true, automation_paused_reason: null },
			'disconnected'
		)
		expect(view).toMatchObject({ kind: 'disconnected', label: 'Not connected', resumeNote: null })
		expect(view.note).toBe(
			'This number is disconnected, so automatic replies are not running. Reconnect it to start them again.'
		)
		expect(view.note).not.toMatch(/Vitevue/)
	})

	it('treats a disconnected number as not connected even when a stale pause reason is present', () => {
		const view = automationView(
			{ ...base, automation_enabled: true, automation_paused_reason: 'assistant_disabled' },
			'disconnected'
		)
		expect(view.kind).toBe('disconnected')
	})

	it('keeps the generic Vitevue pause for a connected number with an unknown reason', () => {
		const view = automationView(
			{ ...base, automation_enabled: true, automation_paused_reason: null },
			'connected'
		)
		expect(view.kind).toBe('paused')
		expect(view.note).toBe('Automatic replies are paused by Vitevue.')
	})

	it('says plainly that nothing is being read when the whole intake is off', () => {
		const view = automationView({
			...base,
			automation_enabled: true,
			automation_paused_reason: 'intake_disabled'
		})
		expect(view.kind).toBe('paused')
		expect(view.note).toMatch(/not reading new WhatsApp messages/)
	})

	it('never shows a raw code for a reason it does not know', () => {
		const view = automationView({
			...base,
			automation_enabled: true,
			automation_paused_reason: 'quota_hit' as never
		})
		expect(view.kind).toBe('paused')
		expect(view.note).not.toMatch(/_/)
	})
})
