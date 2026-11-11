import { afterEach, describe, expect, it, vi } from 'vitest'

import {
	createSignupCollector,
	describeCompleteError,
	isFacebookOrigin,
	type SignupResult
} from '$lib/whatsapp/signup'

const ids = {
	phone_number_id: 'phone-1',
	waba_id: 'waba-1',
	business_id: 'biz-1'
}

function finish(event = 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING', data: object = ids) {
	return { type: 'WA_EMBEDDED_SIGNUP', event, data }
}

function setup() {
	const done: SignupResult[] = []
	const stops: { kind: string; message: string }[] = []
	const collector = createSignupCollector({
		onComplete: (r) => done.push(r),
		onStop: (kind, message) => stops.push({ kind, message })
	})
	return { collector, done, stops }
}

afterEach(() => vi.useRealTimers())

describe('isFacebookOrigin', () => {
	it('accepts facebook.com and its subdomains only', () => {
		expect(isFacebookOrigin('https://www.facebook.com')).toBe(true)
		expect(isFacebookOrigin('https://business.facebook.com')).toBe(true)
		expect(isFacebookOrigin('https://facebook.com')).toBe(true)
		expect(isFacebookOrigin('https://evilfacebook.com')).toBe(false)
		expect(isFacebookOrigin('https://facebook.com.evil.example')).toBe(false)
		expect(isFacebookOrigin('http://www.facebook.com')).toBe(false)
		expect(isFacebookOrigin('not a url')).toBe(false)
	})
})

describe('signup collector', () => {
	it('completes when the code arrives before the ids', () => {
		const { collector, done } = setup()
		collector.handleLogin({ authResponse: { code: 'code-1' } })
		expect(done).toEqual([])
		collector.handleMessage({ origin: 'https://www.facebook.com', data: JSON.stringify(finish()) })
		expect(done).toEqual([
			{ code: 'code-1', event: 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING', ...ids }
		])
	})

	it('completes when the ids arrive before the code', () => {
		const { collector, done } = setup()
		collector.handleMessage({ origin: 'https://business.facebook.com', data: finish('FINISH') })
		expect(done).toEqual([])
		collector.handleLogin({ authResponse: { code: 'code-2' } })
		expect(done).toHaveLength(1)
		expect(done[0]).toMatchObject({ code: 'code-2', event: 'FINISH', waba_id: 'waba-1' })
	})

	it('completes once even if Meta repeats the finish message', () => {
		const { collector, done } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: finish() })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: finish() })
		expect(done).toHaveLength(1)
	})

	it('ignores messages from other origins', () => {
		const { collector, done, stops } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({ origin: 'https://evil.example', data: finish() })
		collector.handleMessage({ origin: 'https://evilfacebook.com', data: finish() })
		expect(done).toEqual([])
		expect(stops).toEqual([])
	})

	it('ignores unrelated message types and unparsable text', () => {
		const { collector, done, stops } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: { type: 'OTHER' } })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: 'plain text' })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: null })
		expect(done).toEqual([])
		expect(stops).toEqual([])
	})

	it('stops with a friendly message when the agent cancels in the pop-up', () => {
		const { collector, done, stops } = setup()
		collector.handleMessage({
			origin: 'https://www.facebook.com',
			data: { type: 'WA_EMBEDDED_SIGNUP', event: 'CANCEL', data: { current_step: 'PHONE_NUMBER' } }
		})
		expect(done).toEqual([])
		expect(stops).toHaveLength(1)
		expect(stops[0].kind).toBe('cancelled')
		expect(stops[0].message).toMatch(/nothing was connected/i)
	})

	it('stops when FB.login returns no code', () => {
		const { collector, stops } = setup()
		collector.handleLogin({ status: 'unknown' })
		expect(stops[0].kind).toBe('cancelled')
	})

	it('stops with Meta’s error text on an ERROR message', () => {
		const { collector, stops } = setup()
		collector.handleMessage({
			origin: 'https://www.facebook.com',
			data: {
				type: 'WA_EMBEDDED_SIGNUP',
				event: 'ERROR',
				data: { error_message: 'Phone number is already registered' }
			}
		})
		expect(stops[0].kind).toBe('error')
		expect(stops[0].message).toContain('Phone number is already registered')
	})

	it('rejects the WABA-only finish event instead of connecting', () => {
		const { collector, done, stops } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({
			origin: 'https://www.facebook.com',
			data: finish('FINISH_ONLY_WABA', { waba_id: 'w' })
		})
		expect(done).toEqual([])
		expect(stops[0].kind).toBe('error')
		expect(stops[0].message).toMatch(/phone number/i)
	})

	it('stops when the finish message lacks the number or account ids', () => {
		const { collector, done, stops } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({
			origin: 'https://www.facebook.com',
			data: finish('FINISH', { waba_id: 'w' })
		})
		expect(done).toEqual([])
		expect(stops[0].kind).toBe('error')
	})

	it('stops if only one half arrives before the wait runs out', () => {
		vi.useFakeTimers()
		const { collector, done, stops } = setup()
		collector.handleLogin({ authResponse: { code: 'c' } })
		vi.advanceTimersByTime(20_000)
		expect(done).toEqual([])
		expect(stops[0].kind).toBe('timeout')
	})

	it('does nothing after it has been cancelled by the page', () => {
		const { collector, done, stops } = setup()
		collector.dispose()
		collector.handleLogin({ authResponse: { code: 'c' } })
		collector.handleMessage({ origin: 'https://www.facebook.com', data: finish() })
		expect(done).toEqual([])
		expect(stops).toEqual([])
	})
})

describe('describeCompleteError', () => {
	it.each([
		[400, /took too long|start again/i],
		[403, /isn.t available|not available/i],
		[409, /already connected/i],
		[422, /existing whatsapp business/i],
		[502, /meta did not accept/i],
		[503, /being set up/i]
	])('explains HTTP %i in plain words', (status, pattern) => {
		expect(describeCompleteError(status)).toMatch(pattern)
	})

	it('falls back to a generic retry message', () => {
		expect(describeCompleteError(500)).toMatch(/try again/i)
		expect(describeCompleteError(0)).toMatch(/internet|try again/i)
	})
})
