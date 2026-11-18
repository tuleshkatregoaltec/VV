import type { EmailLead, EmailSendStatus, Tone } from './api/types'

/** Connectors › Email: send status words and colours, times, lead labels and token previews. */

export const SEND_STATUS: Record<EmailSendStatus, { label: string; tone: Tone }> = {
	queued: { label: 'Queued', tone: 'neutral' },
	sent: { label: 'Sent', tone: 'neutral' },
	deferred: { label: 'Deferred', tone: 'amber' },
	delivered: { label: 'Delivered', tone: 'blue' },
	opened: { label: 'Opened', tone: 'green' },
	clicked: { label: 'Clicked', tone: 'green' },
	bounced: { label: 'Bounced', tone: 'red' },
	spam: { label: 'Spam', tone: 'red' },
	unsubscribed: { label: 'Unsubscribed', tone: 'amber' },
	failed: { label: 'Failed', tone: 'red' },
	replied: { label: 'Replied', tone: 'green' }
}

/** Tracking filter order: the happy path first, then the problems. */
export const SEND_STATUS_ORDER: EmailSendStatus[] = [
	'sent',
	'delivered',
	'opened',
	'clicked',
	'replied',
	'deferred',
	'bounced',
	'spam',
	'unsubscribed',
	'failed'
]

/** Names for the canonical event keys the backend stores. */
export const EVENT_LABEL: Record<string, string> = {
	request: 'Sent',
	sent: 'Sent',
	delivered: 'Delivered',
	deferred: 'Deferred',
	opened: 'Opened',
	uniqueopened: 'Opened (first)',
	loadedbyproxy: 'Opened by mail privacy proxy',
	proxyopen: 'Opened by mail privacy proxy',
	click: 'Clicked',
	clicked: 'Clicked',
	softbounce: 'Soft bounce',
	hardbounce: 'Hard bounce',
	blocked: 'Blocked',
	invalidemail: 'Invalid address',
	error: 'Error',
	spam: 'Marked as spam',
	complaint: 'Marked as spam',
	unsubscribed: 'Unsubscribed',
	replied: 'Replied'
}

/** "28 Oct, 14:05" in the viewer's time zone. */
export function stamp(iso: string | null): string {
	if (!iso) return '—'
	const d = new Date(iso)
	if (Number.isNaN(d.getTime())) return '—'
	return d.toLocaleString('en-GB', {
		day: 'numeric',
		month: 'short',
		hour: '2-digit',
		minute: '2-digit'
	})
}

/** Lead type by intent, in the Leads page's words. */
export const INTENT_LABEL: Record<EmailLead['intent'], string> = {
	buy: 'Buyer',
	rent: 'Tenant',
	sell: 'Seller',
	let: 'Landlord',
	unknown: 'Not typed yet'
}

/** The Type filter: every intent, typed ones first. */
export const INTENT_ORDER: EmailLead['intent'][] = ['buy', 'rent', 'sell', 'let', 'unknown']

/** A template's types in words: "Buyer, Tenant", or "All types" when it suits every lead. */
export const typesLabel = (types: EmailLead['intent'][]) =>
	types.length
		? INTENT_ORDER.filter((t) => types.includes(t))
				.map((t) => INTENT_LABEL[t])
				.join(', ')
		: 'All types'

/** Whether a template suits any of these lead types (a template with no types suits all). */
export const suits = (types: EmailLead['intent'][], intents: EmailLead['intent'][]) =>
	!types.length || intents.some((i) => types.includes(i))

/** A backend lead status as words: "closed_lost" → "Closed lost". */
export const statusLabel = (s: string) =>
	(s.charAt(0).toUpperCase() + s.slice(1)).replace(/_/g, ' ')

/** The backend's {{token}} filling, for previews. Unknown tokens stay as written. */
export function fillTokens(text: string, p: { name: string; email: string }) {
	const values: Record<string, string> = {
		name: p.name,
		first_name: p.name.split(/\s+/)[0] ?? '',
		email: p.email
	}
	return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (whole, key: string) => values[key] ?? whole)
}

export type MessagePart =
	| { kind: 'text'; text: string }
	| { kind: 'link'; text: string; url: string }
	| { kind: 'button'; text: string; url: string }

/**
 * The backend's link rules (brevo.LINKS), for previews: [button: Label](https://…) is a button,
 * [text](https://…) a link, a bare https://… URL a link. Only http(s) targets become clickable.
 * Returns paragraphs (split on blank lines) of parts.
 */
const LINKS =
	/\[button:\s*([^\]\n]+?)\s*\]\((https?:\/\/[^\s)]+)\)|\[([^\]\n]+?)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>()]+[^\s<>().,;:!?'"])/g

export function messageParts(text: string): MessagePart[][] {
	return text
		.trim()
		.split(/\n\s*\n/)
		.filter((p) => p.trim())
		.map((p) => {
			const parts: MessagePart[] = []
			let last = 0
			for (const m of p.matchAll(LINKS)) {
				if (m.index > last) parts.push({ kind: 'text', text: p.slice(last, m.index) })
				if (m[1]) parts.push({ kind: 'button', text: m[1], url: m[2] })
				else if (m[3]) parts.push({ kind: 'link', text: m[3], url: m[4] })
				else parts.push({ kind: 'link', text: m[5], url: m[5] })
				last = m.index + m[0].length
			}
			if (last < p.length) parts.push({ kind: 'text', text: p.slice(last) })
			return parts
		})
}
