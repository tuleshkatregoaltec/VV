/**
 * Sample WhatsApp data for building the UI before the Cloud API backend exists. Only in
 * `bun run dev` with VITE_WHATSAPP_DEMO=1; a build never shows it. Remove with the backend.
 * Chats on real leads are written from the lead itself (name, type, what they want, area,
 * budget) so the conversation reads true for that lead.
 */
import type {
	LeadRow,
	WhatsAppChat,
	WhatsAppMessage,
	WhatsAppStatus,
	WhatsAppTemplate,
	WhatsAppThread
} from './types'

export const WHATSAPP_DEMO = import.meta.env.DEV && import.meta.env.VITE_WHATSAPP_DEMO === '1'

const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString()
const inHours = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString()

export const demoStatus: WhatsAppStatus = {
	configured: true,
	connected: true,
	business_name: 'Vitevue',
	display_number: '+971 4 123 4567'
}

export const demoTemplates: WhatsAppTemplate[] = [
	{
		name: 'property_follow_up',
		language: 'en_US',
		category: 'marketing',
		review: 'approved',
		body: 'Hi {{1}}, are you still interested in a {{2}} in {{3}}? Reply here and we can help.'
	},
	{
		name: 'viewing_reminder',
		language: 'en_US',
		category: 'utility',
		review: 'approved',
		body: 'Hi {{1}}, a reminder of your viewing at {{2}} on {{3}}. Reply to reschedule.'
	},
	{
		name: 'new_listing_alert',
		language: 'ar',
		category: 'marketing',
		review: 'pending',
		body: 'مرحبا {{1}}، لدينا عقار جديد في {{2}} قد يناسبك.'
	},
	{
		name: 'price_drop',
		language: 'en_US',
		category: 'marketing',
		review: 'rejected',
		body: 'Great news {{1}}! Prices just dropped — act now!'
	}
]

type DemoLead = Pick<LeadRow, 'id' | 'name' | 'phone' | 'lead_type' | 'area' | 'summary'>

/** "ALEXANDRU ION TIRIAC" → "Alexandru". */
const firstName = (name: string) => {
	const w = name.trim().split(/\s+/)[0] ?? ''
	return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
}

/** The WhatsApp id for a lead's phone: digits only, as Meta sends it. */
export const demoWaId = (l: DemoLead) => l.phone.replace(/\D/g, '') || `9715000${l.id}`

/** Half the sample leads have just written back (unread, last message theirs). */
const repliedLast = (l: DemoLead) => l.id % 2 === 0

/** The lead's side and ours, by lead type; `want` and `budget` come from the lead's Details. */
function script(l: DemoLead): [string, string, string, string] {
	const f = firstName(l.name)
	const want = l.summary.line && l.summary.line !== 'Not stated' ? l.summary.line : ''
	const budget = l.summary.sub
	const area = l.area || 'your area'
	switch (l.lead_type) {
		case 'tenant':
			return [
				`Hi ${f}, this is Vitevue. Are you still looking for ${want ? `a ${want}` : `a place to rent in ${area}`}? Reply here and we can help.`,
				`Yes, still looking. ${budget ? `Ideally around ${budget}.` : 'What do you have?'}`,
				`I have a few options in ${area} that fit. Shall I send photos and set up viewings?`,
				'Please do. Evenings work best for me.'
			]
		case 'landlord':
			return [
				`Hi ${f}, this is Vitevue. We have tenants asking for ${area}. Is your property available to rent?`,
				'It will be free from next month.',
				`Great. I can list it and line up viewings. What rent are you expecting${budget ? ` — around ${budget}` : ''}?`,
				'Yes, roughly that. Send me the next steps.'
			]
		case 'seller':
		case 'owner':
			return [
				`Hi ${f}, this is Vitevue. We have buyers asking about ${area}. Would you consider selling${want ? ` your ${want}` : ''}?`,
				'Maybe. What price could I get?',
				`Similar units in ${area} sold recently. I can send you a free valuation today.`,
				'OK, send it over.'
			]
		default:
			if (!want && !l.area)
				return [
					`Hi ${f}, this is Vitevue. Thanks for getting in touch. Are you looking to buy at the moment?`,
					'Yes, a 2 bed somewhere near Dubai Marina or JLT.',
					'Great, I have a few options there. What budget should I work with?',
					'Around AED 2m. Can we see some this week?'
				]
			return [
				`Hi ${f}, this is Vitevue. Are you still looking for ${want ? `a ${want}` : `a property in ${area}`}? Reply here and we can help.`,
				`Yes, still looking.${budget ? ` Budget is around ${budget}.` : ''} What do you have?`,
				`I have two units in ${area} that fit. Can I send the details and book a viewing this week?`,
				'Yes please, send them over. Saturday works for me.'
			]
	}
}

const msg = (
	id: string,
	direction: 'in' | 'out',
	body: string,
	minutesAgo: number,
	status: WhatsAppMessage['status'] = null,
	template: string | null = null
): WhatsAppMessage => ({ id, direction, body, at: ago(minutesAgo), status, template, error: null })

/** A short chat with this lead: an opening message, their answer, our reply (and maybe theirs). */
export function demoThreadFor(l: DemoLead): WhatsAppThread {
	const [opening, answer, ours, back] = script(l)
	const k = `wamid.demo.${l.id}`
	const messages = [
		msg(`${k}.1`, 'out', opening, 70, 'read', 'property_follow_up'),
		msg(`${k}.2`, 'in', answer, 64),
		msg(`${k}.3`, 'out', ours, 12, repliedLast(l) ? 'read' : 'delivered')
	]
	if (repliedLast(l)) messages.push(msg(`${k}.4`, 'in', back, 4))
	const lastIn = repliedLast(l) ? 4 : 64
	return {
		wa_number: `+${demoWaId(l)}`,
		opted_out: false,
		window_ends_at: inHours(24 - lastIn / 60),
		messages
	}
}

/** The chat row for a sample lead, from its thread. */
export function demoChatFor(l: LeadRow): WhatsAppChat {
	const t = demoThreadFor(l)
	const last = t.messages[t.messages.length - 1]
	return {
		wa_id: demoWaId(l),
		contact_name: firstName(l.name),
		lead_id: l.id,
		lead_name: l.name,
		lead_stage: l.stage,
		lead_score: l.score,
		lead_source: l.source,
		lead_source_short: l.source_short,
		last_body: last.body,
		last_direction: last.direction,
		last_at: last.at,
		window_ends_at: t.window_ends_at,
		unread: last.direction === 'in' ? 1 : 0
	}
}

/** A number that wrote in and matches no lead (Needs review); the 24 hours have passed. */
export const demoUnmatchedChat: WhatsAppChat = {
	wa_id: '447700900123',
	contact_name: null,
	lead_id: null,
	lead_name: null,
	lead_stage: null,
	lead_score: null,
	lead_source: null,
	lead_source_short: null,
	last_body: 'Hi, is the 1 bed in Business Bay still available? What is the yearly rent?',
	last_direction: 'in',
	last_at: ago(60 * 30),
	window_ends_at: null,
	unread: 0
}

export const demoUnmatchedThread: WhatsAppThread = {
	wa_number: '+44 7700 900123',
	opted_out: false,
	window_ends_at: null,
	messages: [msg('wamid.demo.u1', 'in', demoUnmatchedChat.last_body, 60 * 30)]
}
