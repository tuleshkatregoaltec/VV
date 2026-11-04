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

/** A campaign recipient: where sending got to, then what Meta reported once sent. */
export const RECIPIENT_STATUS: Record<string, { label: string; tone: Tone }> = {
	pending: { label: 'Waiting', tone: 'neutral' },
	sending: { label: 'Sending', tone: 'neutral' },
	queued: { label: 'Sent', tone: 'neutral' },
	sent: { label: 'Sent', tone: 'neutral' },
	delivered: { label: 'Delivered', tone: 'blue' },
	read: { label: 'Read', tone: 'green' },
	failed: { label: 'Failed', tone: 'red' },
	skipped: { label: 'Skipped', tone: 'amber' },
	unknown: { label: 'Check chat', tone: 'amber' }
}

/** The campaign value that becomes each recipient's own first name. */
export const FIRST_NAME = '{first_name}'

/** How many values an opening message needs: its highest {{n}}. */
export const variableCount = (body: string) =>
	Math.max(0, ...[...body.matchAll(/\{\{\s*(\d+)\s*\}\}/g)].map((m) => Number(m[1])))

/** An opening message with the agent's values in place; a value not given yet shows as "…". */
export const fillValues = (body: string, values: string[]) =>
	body.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, n) => values[Number(n) - 1]?.trim() || '…')

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
