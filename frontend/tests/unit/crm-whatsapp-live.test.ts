import { describe, expect, it } from 'vitest'

import { crmKeys } from '$lib/crm/queries'
import { liveUrl, showsChat } from '$lib/crm/whatsappLive'

describe('WhatsApp live updates', () => {
	it('connects to the same API host over ws/wss, so production stays encrypted', () => {
		expect(liveUrl('http://localhost:8000')).toBe('ws://localhost:8000/api/v1/crm/whatsapp/live')
		expect(liveUrl('https://api.vitevue.com')).toBe(
			'wss://api.vitevue.com/api/v1/crm/whatsapp/live'
		)
	})

	it('refreshes every screen that shows the changed chat, so a new message appears without a reload', () => {
		const wa = '919111622120'
		for (const key of [
			crmKeys.whatsappChats(),
			crmKeys.whatsappCampaignChats(),
			crmKeys.whatsappChat(wa),
			crmKeys.whatsappCampaignChat(wa),
			crmKeys.whatsappThread(42),
			crmKeys.whatsappCampaign(7)
		]) {
			expect(showsChat(key, wa), JSON.stringify(key)).toBe(true)
		}
	})

	it('leaves other chats and the costly setup screens alone', () => {
		const wa = '919111622120'
		expect(showsChat(crmKeys.whatsappChat('971500000000'), wa)).toBe(false)
		expect(showsChat(crmKeys.whatsappCampaignChat('971500000000'), wa)).toBe(false)
		// Meta's own number list is a live call to Meta; templates and numbers do not change with a chat.
		expect(showsChat(crmKeys.whatsappMetaNumbers(), wa)).toBe(false)
		expect(showsChat(crmKeys.whatsappTemplates(), wa)).toBe(false)
		expect(showsChat(crmKeys.whatsappNumbers(), wa)).toBe(false)
	})

	it('after a reconnect refreshes every open chat, since messages may have arrived meanwhile', () => {
		expect(showsChat(crmKeys.whatsappChat('971500000000'), null)).toBe(true)
	})
})
