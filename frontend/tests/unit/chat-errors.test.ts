import { describe, expect, it } from 'vitest'
import { describeChatError } from '../../src/lib/chat/errors'
import { applyTurnEvent } from '../../src/lib/chat/toolLabels'

// Every failure used to read "The assistant could not complete this request. Please try
// again." The message now follows the stable code the server or stream client sends.
const GENERIC = 'The assistant could not complete this request. Please try again.'

// Every code the backend sends (backend/app/chat/errors.py ERRORS) and the stream client adds.
const SERVER_CODES = [
	'conversation_not_found',
	'assistant_disabled',
	'account_unavailable',
	'turn_in_progress',
	'service_busy',
	'insufficient_allowance',
	'daily_limit_reached',
	'turn_budget_exceeded',
	'provider_rate_limited',
	'provider_unavailable',
	'provider_timeout',
	'provider_invalid_response',
	'internal_error'
]
const CLIENT_CODES = [
	'session_expired',
	'access_denied',
	'invalid_request',
	'server_unavailable',
	'stream_interrupted',
	'network_error'
]

describe('each failure says what happened', () => {
	it.each(
		[...SERVER_CODES, ...CLIENT_CODES].filter((code) => code !== 'internal_error')
	)('%s has its own message, not the generic one', (code) => {
		expect(describeChatError({ type: 'error', code }).message).not.toBe(GENERIC)
	})

	it('gives every code a distinct message', () => {
		const messages = [...SERVER_CODES, ...CLIENT_CODES].map(
			(code) => describeChatError({ code }).message
		)
		expect(new Set(messages).size).toBe(messages.length)
	})

	it('explains a per-turn budget stop by asking for a narrower question', () => {
		expect(describeChatError({ code: 'turn_budget_exceeded' }).message).toContain(
			'one area, project or record'
		)
	})

	it('shows the daily usage, limit and reset time, and opens the limit dialog', () => {
		const view = describeChatError({
			code: 'daily_limit_reached',
			tokens_used: 1_000_000,
			daily_limit: 1_000_000,
			resets_at: '2026-11-26T00:00:00+00:00'
		})
		expect(view.message).toBe(
			"You have used today's assistant allowance (1,000,000 of 1,000,000 tokens used). It resets 26 Nov, 04:00 Dubai time."
		)
		expect(view).toMatchObject({ dailyLimit: true, retry: false })
	})

	it('says when there is not enough allowance left for a new answer', () => {
		const view = describeChatError({
			code: 'insufficient_allowance',
			resets_at: '2026-11-26T00:00:00+00:00'
		})
		expect(view.message).toContain('Not enough of today')
		expect(view.message).toContain('It resets 26 Nov, 04:00 Dubai time.')
		expect(view.dailyLimit).toBe(false)
	})

	it('offers retry only where sending again is safe', () => {
		const retry = (code: string) => describeChatError({ code }).retry
		for (const code of [
			'turn_in_progress',
			'service_busy',
			'provider_rate_limited',
			'provider_unavailable',
			'provider_timeout'
		])
			expect(retry(code), code).toBe(true)
		for (const code of [
			'turn_budget_exceeded',
			'daily_limit_reached',
			'insufficient_allowance',
			'access_denied',
			'session_expired',
			'stream_interrupted',
			'network_error'
		])
			expect(retry(code), code).toBe(false)
	})

	it('treats a broken connection as possibly still running: reload, do not resend', () => {
		for (const code of ['stream_interrupted', 'network_error']) {
			const view = describeChatError({ code })
			expect(view).toMatchObject({ retry: false, reloadConversation: true })
			expect(view.message).toContain('may still finish')
		}
		expect(describeChatError({ code: 'provider_unavailable' }).reloadConversation).toBe(false)
	})

	it('falls back to the generic safe message for an unknown or missing code', () => {
		for (const event of [{ code: 'something_new' }, {}, { error: 'raw text from somewhere' }]) {
			const view = describeChatError(event)
			expect(view.message).toBe(GENERIC)
			expect(view.retry).toBe(false)
		}
	})

	it('never shows the raw error text the event carries', () => {
		const view = describeChatError({
			code: 'provider_unavailable',
			error: 'sk-or-v1-secret SELECT * FROM crm'
		})
		expect(view.message).not.toContain('SELECT')
		expect(view.message).not.toContain('sk-or')
	})

	it('adds the server reference to an unexpected failure so support can find it', () => {
		expect(describeChatError({ code: 'internal_error', reference: 'a1b2c3d4e5f6' }).message).toBe(
			`${GENERIC} (Reference a1b2c3d4e5f6)`
		)
	})

	it('accepts the legacy token_limit_exceeded event as the daily limit', () => {
		expect(describeChatError({ error: 'token_limit_exceeded' }).dailyLimit).toBe(true)
	})
})

describe('the working status clears on every ending', () => {
	it.each(['done', 'error'])('a %s event clears it, with no answer invented', (type) => {
		let view = applyTurnEvent({ answer: '', status: null }, { type: 'thinking' })
		view = applyTurnEvent(view, { type: 'tool_call_start', tool: 'retrieve_personal_crm' })
		expect(view.status).toBe('Reviewing your CRM…')
		view = applyTurnEvent(view, { type })
		expect(view).toEqual({ answer: '', status: null })
	})
})
