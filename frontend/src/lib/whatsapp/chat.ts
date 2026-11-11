import type { CustomerMessageResponse, ThreadResponse } from '$lib/api/generated/hey-api/types.gen'
import { reasonLabel } from './handoff'

/** One row of the chat mirror, in the order the customer experienced it. */
export type ChatItem =
	| { kind: 'day'; key: string; label: string }
	| { kind: 'in'; key: string; text: string | null; at: string }
	| {
			kind: 'out'
			key: string
			text: string
			at: string
			state: 'sent' | 'queued' | 'failed'
			note: string | null
	  }
	| { kind: 'draft'; key: string; message: CustomerMessageResponse }
	| { kind: 'discarded'; key: string; text: string; note: string }
	| { kind: 'handoff'; key: string; text: string }
	| { kind: 'quiet'; key: string; text: string }
	| { kind: 'typing'; key: string }

const SENT = new Set(['accepted', 'sent'])
const QUEUED = new Set(['auto_pending', 'approved', 'sending', 'queued'])
const WORKING = new Set(['received', 'queued', 'classifying', 'drafting'])
const FAILED: Record<string, string> = {
	failed: 'Not sent. WhatsApp refused this reply.',
	unknown: 'Send not confirmed. Check WhatsApp before sending again.',
	expired: 'Not sent. The 24-hour reply window closed.'
}

const COUNTRY = ['971', '966', '974', '965', '973', '968', '91', '44', '1']
const GROUPS: Record<string, number[]> = {
	'971': [2, 3, 4],
	'91': [5, 5],
	'44': [4, 6],
	'1': [3, 3, 4]
}

/** "971501279179" -> "+971 50 127 9179". Unknown country codes fall back to plain groups. */
export function formatPhone(digits: string): string {
	const clean = digits.replace(/\D/g, '')
	const cc = COUNTRY.find((code) => clean.startsWith(code))
	if (!cc) return `+${clean}`
	let rest = clean.slice(cc.length)
	const parts: string[] = []
	// UAE landlines have a one-digit area code (04 Dubai); mobiles start with 5.
	const groups = cc === '971' && !rest.startsWith('5') ? [1, 3, 4] : (GROUPS[cc] ?? [3, 3, 4])
	for (const size of groups) {
		if (!rest) break
		parts.push(rest.slice(0, size))
		rest = rest.slice(size)
	}
	if (rest) parts.push(rest)
	return `+${cc} ${parts.join(' ')}`
}

/** Two characters for the avatar: the last two digits read like a name in a long list. */
export function avatarText(sender: string): string {
	return sender.replace(/\D/g, '').slice(-2) || '··'
}

function dayKey(iso: string): string {
	const d = new Date(iso)
	return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

export function dayLabel(iso: string, now = new Date()): string {
	const d = new Date(iso)
	const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
	const diff = Math.round((start(now) - start(d)) / 86_400_000)
	if (diff === 0) return 'Today'
	if (diff === 1) return 'Yesterday'
	return d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

export function clock(iso: string): string {
	return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

function byTime(a: CustomerMessageResponse, b: CustomerMessageResponse) {
	return a.sent_at.localeCompare(b.sent_at) || a.created_at.localeCompare(b.created_at)
}

/** Turn stored message rows (customer text + the reply decided for it) into chat bubbles. */
export function buildTranscript(
	rows: readonly CustomerMessageResponse[],
	now = new Date()
): ChatItem[] {
	const items: ChatItem[] = []
	const ordered = [...rows].sort(byTime)
	let lastDay = ''
	ordered.forEach((m, index) => {
		const day = dayKey(m.sent_at)
		if (day !== lastDay) {
			items.push({ kind: 'day', key: `day:${day}`, label: dayLabel(m.sent_at, now) })
			lastDay = day
		}
		items.push({ kind: 'in', key: `in:${m.id}`, text: m.content, at: m.sent_at })
		const replyAt = m.send_after ?? m.updated_at
		const isLast = index === ordered.length - 1
		if (SENT.has(m.status) && m.reply) {
			items.push({
				kind: 'out',
				key: `out:${m.id}`,
				text: m.reply,
				at: replyAt,
				state: 'sent',
				note: null
			})
		} else if (QUEUED.has(m.status) && m.reply) {
			items.push({
				kind: 'out',
				key: `out:${m.id}`,
				text: m.reply,
				at: replyAt,
				state: 'queued',
				note: null
			})
		} else if (m.status in FAILED) {
			if (m.reply) {
				items.push({
					kind: 'out',
					key: `out:${m.id}`,
					text: m.reply,
					at: replyAt,
					state: 'failed',
					note: FAILED[m.status]
				})
			} else {
				items.push({ kind: 'quiet', key: `q:${m.id}`, text: FAILED[m.status] })
			}
		} else if (m.status === 'approval_required') {
			if (m.handoff_summary)
				items.push({ kind: 'handoff', key: `h:${m.id}`, text: m.handoff_summary })
			items.push({ kind: 'draft', key: `d:${m.id}:${m.revision}`, message: m })
		} else if (m.status === 'cancelled') {
			if (m.handoff_summary)
				items.push({ kind: 'handoff', key: `h:${m.id}`, text: m.handoff_summary })
			if (m.reply) {
				items.push({
					kind: 'discarded',
					key: `x:${m.id}`,
					text: m.reply,
					note: reasonLabel(m.reason) ?? 'Draft cancelled'
				})
			}
		} else if (m.status === 'ignored') {
			items.push({
				kind: 'quiet',
				key: `q:${m.id}`,
				text: 'No automatic reply. Not a property question.'
			})
		} else if (WORKING.has(m.status) && isLast) {
			items.push({ kind: 'typing', key: `t:${m.id}` })
		}
	})
	return items
}

export type ThreadState = 'review' | 'yours' | 'auto' | 'optout'

export function threadState(
	thread: Pick<ThreadResponse, 'paused' | 'opted_out' | 'id'>,
	pendingThreads: ReadonlySet<string>
): ThreadState {
	if (thread.opted_out) return 'optout'
	if (pendingThreads.has(thread.id)) return 'review'
	if (thread.paused) return 'yours'
	return 'auto'
}

export const THREAD_STATE_LABEL: Record<ThreadState, string> = {
	review: 'Needs your approval',
	yours: 'You’re handling this',
	auto: 'Assistant replying',
	optout: 'Opted out'
}
