import type { Tone, WhatsAppChat, WhatsAppMessageStatus } from './api/types'
import { scoreClass } from './config'

/** Connectors › WhatsApp: status words and colours and the service window. */

export const MESSAGE_STATUS: Record<WhatsAppMessageStatus, { label: string; tone: Tone }> = {
	queued: { label: 'Queued', tone: 'neutral' },
	sent: { label: 'Sent', tone: 'neutral' },
	delivered: { label: 'Delivered', tone: 'blue' },
	read: { label: 'Read', tone: 'green' },
	failed: { label: 'Failed', tone: 'red' }
}

/** Hours left in the 24-hour customer-service window; 0 when closed or never opened. */
export function windowHoursLeft(endsAt: string | null, now = Date.now()): number {
	if (!endsAt) return 0
	const ms = new Date(endsAt).getTime() - now
	return ms > 0 ? Math.ceil(ms / 3_600_000) : 0
}

/** "property_follow_up" → "Property follow up": an opening message's name for agents. */
export const messageTitle = (name: string) => {
	const words = name.replace(/_/g, ' ').trim()
	return words.charAt(0).toUpperCase() + words.slice(1)
}

/** An opening message as the contact will read it: {{1}} is their first name, the rest is filled when sent. */
export const fillPreview = (body: string, firstName: string | null) =>
	body.replace(/\{\{(\d+)\}\}/g, (_, n) => (n === '1' && firstName ? firstName : '…'))

/** A lead's score as a chance to close, in the same bands as the score chip. */
export const potential = (score: number) => {
	const band = scoreClass(score)
	return { label: band === '' ? 'High' : band === 'mid' ? 'Medium' : 'Low', band }
}

/** One name per chat: the lead's when the number is on a lead, else the WhatsApp profile name or number. */
export const chatName = (c: WhatsAppChat) => c.lead_name ?? c.contact_name ?? `+${c.wa_id}`

/** "+971501234567 · WhatsApp: Sara": the number, and the profile name only when it differs. */
export const chatSub = (c: WhatsAppChat) =>
	c.contact_name && c.contact_name !== chatName(c)
		? `+${c.wa_id} · WhatsApp: ${c.contact_name}`
		: chatName(c) === `+${c.wa_id}`
			? ''
			: `+${c.wa_id}`
