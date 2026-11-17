import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'

vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

async function receive(body: string) {
	vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(body)))
	const events: Array<{ type: string; error?: string; content?: string }> = []
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
			{ type: 'error', error: 'Stream ended before completion. Please try again.' }
		])
	})

	it('preserves the server failure without manufacturing success', async () => {
		expect(await receive('data: {"type":"error","error":"Capacity exhausted"}\n\n')).toEqual([
			{ type: 'error', error: 'Capacity exhausted' }
		])
	})

	it('does not treat a heartbeat-only response as an answer', async () => {
		expect(await receive(': keep-alive\n\n')).toEqual([
			{ type: 'error', error: 'Stream ended before completion. Please try again.' }
		])
	})
})
