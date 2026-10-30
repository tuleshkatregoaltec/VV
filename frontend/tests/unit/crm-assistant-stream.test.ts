import { describe, expect, it } from 'vitest'

import { type AssistantEvent, applyEvent, type ThreadMessage } from '$lib/crm/assistant/stream'

// The thread is rebuilt from SSE events: text arrives in pieces, a status line shows what the
// assistant is doing, and proposed changes become cards on the reply they belong to.
const start = (): ThreadMessage[] => [
	{ role: 'user', content: 'Move Ahmed to qualified', actions: [] },
	{ role: 'assistant', content: '', actions: [] }
]
const fold = (events: AssistantEvent[]) => events.reduce(applyEvent, start())

const action = {
	action_id: 'a1',
	action_type: 'status' as const,
	lead_id: 7,
	summary: 'Move Ahmed Khan to qualified',
	before: { status: 'contacted' },
	after: { status: 'qualified' },
	status: 'pending' as const
}

describe('assistant stream', () => {
	it('joins text deltas into the reply', () => {
		const thread = fold([
			{ type: 'text-delta', content: 'Ahmed is ' },
			{ type: 'text-delta', content: '**contacted**.' }
		])
		expect(thread.at(-1)?.content).toBe('Ahmed is **contacted**.')
		expect(thread[0].content).toBe('Move Ahmed to qualified')
	})

	it('shows what the assistant is doing until the turn is done', () => {
		const working = fold([{ type: 'tool-status', tool: 'search_leads', label: 'Searching leads…' }])
		expect(working.at(-1)?.status).toBe('Searching leads…')
		const done = fold([
			{ type: 'tool-status', tool: 'search_leads', label: 'Searching leads…' },
			{ type: 'done' }
		])
		expect(done.at(-1)?.status).toBeUndefined()
	})

	it('attaches a proposed change to the current reply', () => {
		const thread = fold([{ type: 'action-proposed', action }])
		expect(thread.at(-1)?.actions).toEqual([action])
		expect(thread[0].actions).toEqual([])
	})

	it('keeps the partial reply when the stream fails', () => {
		const thread = fold([
			{ type: 'text-delta', content: 'Looking' },
			{ type: 'error', error: 'Something went wrong' }
		])
		expect(thread.at(-1)?.content).toBe('Looking')
		expect(thread.at(-1)?.error).toBe('Something went wrong')
	})

	it('does not change the messages it was given', () => {
		const before = start()
		applyEvent(before, { type: 'text-delta', content: 'x' })
		expect(before.at(-1)?.content).toBe('')
	})
})
