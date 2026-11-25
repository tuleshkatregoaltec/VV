import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'

vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

async function receive(body: string | Response) {
	vi.stubGlobal(
		'fetch',
		vi.fn().mockResolvedValue(typeof body === 'string' ? new Response(body) : body)
	)
	const events: Array<Record<string, unknown> & { type: string }> = []
	await client.stream('/api/v1/chat/conversations/1/messages/stream', (data) => {
		events.push(JSON.parse(data))
	})
	await vi.waitFor(() =>
		expect(events.some((event) => ['done', 'error'].includes(event.type))).toBe(true)
	)
	return events
}

afterEach(() => vi.unstubAllGlobals())

describe('chat stream completion', () => {
	it('ignores heartbeat comments while waiting for an explicit completed answer', async () => {
		expect(
			await receive(
				': keep-alive\n\ndata: {"type":"content","content":"Validated answer"}\n\n: keep-alive\n\ndata: {"type":"done"}\n\n'
			)
		).toEqual([{ type: 'content', content: 'Validated answer' }, { type: 'done' }])
	})

	it('reports an interrupted answer instead of presenting a successful completion', async () => {
		expect(await receive('data: {"type":"content","content":"Partial answer"}\n\n')).toEqual([
			{ type: 'content', content: 'Partial answer' },
			{
				type: 'error',
				code: 'stream_interrupted',
				error: 'Stream ended before completion. Please try again.'
			}
		])
	})

	it('preserves the server failure without manufacturing success', async () => {
		expect(await receive('data: {"type":"error","error":"Capacity exhausted"}\n\n')).toEqual([
			{ type: 'error', error: 'Capacity exhausted' }
		])
	})

	it('does not treat a heartbeat-only response as an answer', async () => {
		expect(await receive(': keep-alive\n\n')).toEqual([
			{
				type: 'error',
				code: 'stream_interrupted',
				error: 'Stream ended before completion. Please try again.'
			}
		])
	})

	it('passes the server code of a refusal before the stream, with its safe figures', async () => {
		const detail = {
			code: 'daily_limit_reached',
			message: "You have used today's assistant allowance.",
			retryable: false,
			tokens_used: 1_000_000,
			daily_limit: 1_000_000,
			resets_at: '2026-11-26T00:00:00+00:00'
		}
		const [event] = await receive(new Response(JSON.stringify({ detail }), { status: 429 }))
		expect(event).toEqual({
			type: 'error',
			code: 'daily_limit_reached',
			error: detail.message,
			retryable: false,
			tokens_used: 1_000_000,
			daily_limit: 1_000_000,
			resets_at: detail.resets_at
		})
	})

	it.each([
		[401, 'session_expired'],
		[403, 'access_denied'],
		[404, 'conversation_not_found'],
		[422, 'invalid_request'],
		[503, 'server_unavailable']
	])('names an HTTP %s refusal without a server code as %s', async (status, code) => {
		const [event] = await receive(new Response('{"detail":"Not allowed"}', { status }))
		expect(event).toMatchObject({ type: 'error', code })
	})

	it('reports a lost connection as a network error, not a server failure', async () => {
		vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
		const events: Array<Record<string, unknown>> = []
		await client.stream('/api/v1/chat/conversations/1/messages/stream', (data) => {
			events.push(JSON.parse(data))
		})
		await vi.waitFor(() => expect(events).toHaveLength(1))
		expect(events[0]).toMatchObject({ type: 'error', code: 'network_error' })
	})
})
