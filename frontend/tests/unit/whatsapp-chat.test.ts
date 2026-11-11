import { describe, expect, it } from 'vitest'

import type { CustomerMessageResponse } from '$lib/api/generated/hey-api/types.gen'
import { buildTranscript, formatPhone, threadState } from '$lib/whatsapp/chat'

const row = (over: Partial<CustomerMessageResponse>): CustomerMessageResponse => ({
	id: 'm1',
	thread_id: 't1',
	content: 'Looking for a 2-bed in Marina',
	sent_at: '2026-11-11T06:33:38Z',
	status: 'accepted',
	reply: 'Are you looking to buy or rent?',
	risk: 'routine',
	topic: 'real_estate',
	reason: null,
	evidence_ids: [],
	handoff_summary: null,
	revision: 1,
	send_after: '2026-11-11T06:33:56Z',
	notification_created_at: null,
	notification_seen_at: null,
	created_at: '2026-11-11T06:33:38Z',
	updated_at: '2026-11-11T06:34:00Z',
	...over
})

const now = new Date('2026-11-11T12:00:00Z')

describe('formatPhone', () => {
	it('groups UAE and Indian numbers the way people write them', () => {
		expect(formatPhone('971501279179')).toBe('+971 50 127 9179')
		expect(formatPhone('919589018092')).toBe('+91 95890 18092')
		expect(formatPhone('97143334444')).toBe('+971 4 333 4444')
	})
})

describe('buildTranscript', () => {
	it('orders oldest first and pairs each message with its sent reply', () => {
		const later = row({
			id: 'm2',
			sent_at: '2026-11-11T06:34:11Z',
			content: 'buy',
			reply: 'Budget?'
		})
		const kinds = buildTranscript([later, row({})], now).map((i) => i.kind)
		expect(kinds).toEqual(['day', 'in', 'out', 'in', 'out'])
	})
	it('shows a held reply as a draft after the hand-off note', () => {
		const held = row({ status: 'approval_required', handoff_summary: 'Wants to buy in January' })
		const items = buildTranscript([held], now)
		expect(items.map((i) => i.kind)).toEqual(['day', 'in', 'handoff', 'draft'])
	})
	it('keeps a cancelled draft visible with its reason', () => {
		const gone = row({ status: 'cancelled', reason: 'human_cancelled' })
		const last = buildTranscript([gone], now).at(-1)
		expect(last).toMatchObject({ kind: 'discarded', note: 'You cancelled this draft' })
	})
	it('shows typing only while the newest message is still being prepared', () => {
		expect(buildTranscript([row({ status: 'classifying', reply: null })], now).at(-1)?.kind).toBe(
			'typing'
		)
	})
	it('marks unsent replies as failed with a plain reason', () => {
		const last = buildTranscript([row({ status: 'expired' })], now).at(-1)
		expect(last).toMatchObject({ kind: 'out', state: 'failed' })
	})
})

describe('threadState', () => {
	it('puts approvals ahead of a paused flag', () => {
		const t = { id: 't1', paused: true, opted_out: false }
		expect(threadState(t, new Set(['t1']))).toBe('review')
		expect(threadState(t, new Set())).toBe('yours')
		expect(threadState({ ...t, opted_out: true }, new Set(['t1']))).toBe('optout')
	})
})
