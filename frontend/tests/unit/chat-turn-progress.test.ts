import { describe, expect, it } from 'vitest'
import { applyTurnEvent, type TurnEvent, type TurnView } from '../../src/lib/chat/toolLabels'

// A CRM answer runs the workflow and several record reads. Each used to add a line such as
// "✓ CRM review complete" or "✓ Your CRM records ready" to the assistant's message, so the
// transcript grew with internal progress. Progress is now one transient status; the message
// holds only the answer.

const ANSWER = 'Bilal Hameed is handled by Track 8.'

function run(events: TurnEvent[]) {
	let view: TurnView = { answer: '', status: null }
	const seen: TurnView[] = []
	for (const event of events) {
		view = applyTurnEvent(view, event)
		seen.push(view)
	}
	return { view, seen }
}

const crmTurn: TurnEvent[] = [
	{ type: 'thinking' },
	{ type: 'tool_call_start', tool: 'retrieve_personal_crm' },
	{ type: 'tool_call_start', tool: 'query_my_crm_records' },
	{ type: 'tool_call_result', tool: 'query_my_crm_records' },
	{ type: 'tool_call_start', tool: 'query_my_crm_records' },
	{ type: 'tool_call_result', tool: 'query_my_crm_records' },
	{ type: 'tool_call_result', tool: 'retrieve_personal_crm' }
]

describe('tool progress stays out of the transcript', () => {
	it('many tool calls leave only the final answer in the message', () => {
		const { view, seen } = run([...crmTurn, { type: 'content', content: ANSWER }, { type: 'done' }])
		expect(view).toEqual({ answer: ANSWER, status: null })
		// While working, the message itself stays empty: no progress line is ever added to it.
		expect(seen.slice(0, crmTurn.length).every((step) => step.answer === '')).toBe(true)
		for (const label of ['complete', 'ready', '✓']) expect(view.answer).not.toContain(label)
	})

	it('shows one compact status at a time, the latest step, never a list', () => {
		const { seen } = run(crmTurn)
		const statuses = seen.map((step) => step.status)
		expect(statuses[0]).toBe('Thinking…')
		expect(statuses[1]).toBe('Reviewing your CRM…')
		expect(statuses[2]).toBe('Reading your CRM records…')
		// A finished read does not add a "ready" line; the status stays one short line.
		expect(statuses.every((status) => typeof status === 'string' && !status.includes('\n'))).toBe(
			true
		)
		expect(statuses.some((status) => status?.includes('ready') || status?.includes('✓'))).toBe(
			false
		)
	})

	it('clears the status when the answer arrives and when the turn ends', () => {
		const answered = run([...crmTurn, { type: 'content', content: ANSWER }])
		expect(answered.view.status).toBeNull()
		const ended = run([...crmTurn, { type: 'done' }])
		expect(ended.view.status).toBeNull()
	})

	it('clears the status when the turn fails, keeping nothing invented as an answer', () => {
		const { view } = run([...crmTurn, { type: 'error' }])
		expect(view).toEqual({ answer: '', status: null })
	})
})
