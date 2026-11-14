import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, client } from '$lib/api/client'

vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

const busy = () =>
	new Response(JSON.stringify({ detail: 'CRM is busy. Retry this request shortly.' }), {
		status: 429,
		headers: { 'Retry-After': '2' }
	})
const ok = () => new Response(JSON.stringify([{ id: 1 }]), { status: 200 })

beforeEach(() => vi.useFakeTimers())
afterEach(() => {
	vi.useRealTimers()
	vi.unstubAllGlobals()
})

describe('CRM admission 429', () => {
	it('retries a read after Retry-After so a busy moment never reaches the panel', async () => {
		const fetch = vi.fn().mockResolvedValueOnce(busy()).mockResolvedValueOnce(ok())
		vi.stubGlobal('fetch', fetch)
		const read = client.get('/api/v1/crm/contact-imports')
		await vi.advanceTimersByTimeAsync(2000)
		expect(await read).toEqual([{ id: 1 }])
		expect(fetch).toHaveBeenCalledTimes(2)
	})

	it('gives up after a bounded number of retries and reports the busy status', async () => {
		const fetch = vi.fn().mockImplementation(async () => busy())
		vi.stubGlobal('fetch', fetch)
		const read = client
			.get('/api/v1/crm/contact-imports')
			.catch((error: ApiError) => error) as Promise<ApiError>
		await vi.advanceTimersByTimeAsync(10_000)
		const error = await read
		expect(error).toBeInstanceOf(ApiError)
		expect(error.status).toBe(429)
		expect(fetch).toHaveBeenCalledTimes(4)
	})

	it('never replays a write, which may not be idempotent', async () => {
		const fetch = vi.fn().mockImplementation(async () => busy())
		vi.stubGlobal('fetch', fetch)
		const write = client
			.post('/api/v1/crm/inbound/enquiries', {})
			.catch((error: ApiError) => error) as Promise<ApiError>
		await vi.advanceTimersByTimeAsync(10_000)
		expect((await write).status).toBe(429)
		expect(fetch).toHaveBeenCalledTimes(1)
	})

	it('does not retry a 429 without Retry-After, such as a used-up daily allowance', async () => {
		const fetch = vi
			.fn()
			.mockResolvedValue(
				new Response(JSON.stringify({ detail: 'Daily token limit' }), { status: 429 })
			)
		vi.stubGlobal('fetch', fetch)
		const read = client
			.get('/api/v1/crm/contact-imports')
			.catch((error: ApiError) => error) as Promise<ApiError>
		await vi.advanceTimersByTimeAsync(10_000)
		expect((await read).message).toBe('Daily token limit')
		expect(fetch).toHaveBeenCalledTimes(1)
	})
})
