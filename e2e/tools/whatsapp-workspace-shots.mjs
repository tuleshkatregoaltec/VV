// Renders the connected /crm/whatsapp workspace (chats, block list, listings, connection) with a
// mocked API and saves PNGs.  node e2e/tools/whatsapp-workspace-shots.mjs <outDir> [baseUrl]
// Needs a running frontend dev server (default http://127.0.0.1:5199).
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from '@playwright/test'

const [outDir = '.', baseUrl = 'http://127.0.0.1:5199'] = process.argv.slice(2)
mkdirSync(outDir, { recursive: true })
const iso = '2026-11-11T06:26:42Z'
const user = {
	id: 'user-1', email: 'agent@example.com', first_name: 'Kian', last_name: 'Agent',
	organization_id: 'org-1', organization_name: 'Acme', role: 'owner', is_owner: true,
	subscription_status: 'active'
}
const session = {
	access_token: 'mock', token_type: 'bearer', expires_in: 3600,
	expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: 'mock',
	user: { id: 'user-1', aud: '', role: 'user', email: user.email, app_metadata: {}, user_metadata: {}, identities: [], created_at: iso }
}
const today = new Date().toISOString().slice(0, 10)
const at = (hm) => `${today}T${hm}:00Z`
const status = {
	state: 'connected', signup_configured: true, connection_id: 'conn-1', phone_number_id: 'p1', waba_id: 'w1',
	business_id: 'b1', display_phone_number: '+971 50 127 9179', display_name: 'Kian Shamsaee',
	onboarding_type: 'env', automation_enabled: true, automation_active: true, automation_paused_reason: null,
	connected_at: iso, disconnected_at: null, last_account_event: null, quality_rating: null,
	can_send_message: 'LIMITED', health_errors: [], payment_method_status: 'unknown',
	contacts: { total: 2, blocked: 2, sync_requested_at: null, synced_at: null }
}
const connection = {
	id: 'conn-1', phone_number_id: 'p1', account_id: 'w1', display_name: 'Kian Shamsaee', enabled: true,
	automation_active: true, automation_paused_reason: null, market_data_enabled: true, approved_knowledge: [],
	reply_voice: null, created_at: iso, updated_at: iso
}
const msg = (id, thread, sent, content, status, reply, o = {}) => ({
	id, thread_id: thread, content, sent_at: at(sent), status, reply, risk: 'routine', topic: 'real_estate',
	reason: null, evidence_ids: [], handoff_summary: null, revision: 1, send_after: at(sent.replace(/:(\d)\d$/, ':$15')),
	notification_created_at: null, notification_seen_at: null, created_at: at(sent), updated_at: at(sent), ...o
})
const threads = [
	{ id: 't1', connection_id: 'conn-1', sender: '919589018092', paused: true, opted_out: false, created_at: at('06:33'), updated_at: at('06:36') },
	{ id: 't2', connection_id: 'conn-1', sender: '971555014422', paused: false, opted_out: false, created_at: at('07:02'), updated_at: at('07:05') },
	{ id: 't3', connection_id: 'conn-1', sender: '447700900123', paused: false, opted_out: false, created_at: at('05:10'), updated_at: at('05:12') }
]
const messages = {
	t1: [
		msg('m1', 't1', '06:33', 'hey i am maan,\nlooking for a two bedroom apartment in marina', 'accepted', 'Hey Maan, are you looking to buy or rent?'),
		msg('m2', 't1', '06:34', 'buy one', 'accepted', 'What’s your budget, and in which currency?'),
		msg('m3', 't1', '06:35', 'around 5 million dirhams', 'accepted', 'Got it, around AED 5 million. When are you looking to move?'),
		msg('m4', 't1', '06:35', 'probably early next year - january first or second week depending when can we get it', 'approval_required', 'Good one, let me look into it and come back to you.', {
			risk: 'approval', notification_created_at: at('06:36'),
			handoff_summary: 'Maan wants to buy a two-bedroom apartment in Marina, budget around AED 5 million, moving in the first or second week of January. Availability for that timing isn’t covered by the facts.'
		})
	],
	t2: [
		msg('n1', 't2', '07:02', 'Hi, what do 1-beds in JVC usually sell for?', 'accepted', 'Recent 1-bed sales in JVC have mostly closed between AED 780k and 1.05M. Are you buying to live in or to rent out?'),
		msg('n2', 't2', '07:05', 'to rent out', 'classifying', null)
	],
	t3: [msg('o1', 't3', '05:10', 'Is this Kian? Call me when free', 'ignored', null, { topic: 'personal' })]
}
const contacts = [
	{ id: 'c1', wa_id: '971501112222', name: null, in_address_book: false, blocked: true, blocked_at: iso, updated_at: iso },
	{ id: 'c2', wa_id: '971559998888', name: null, in_address_book: false, blocked: true, blocked_at: iso, updated_at: iso }
]
const vcf = 'BEGIN:VCARD\nFN:Mum\nTEL:+971 50 111 2222\nEND:VCARD\nBEGIN:VCARD\nFN:Ahmed (Gym)\nTEL:055 999 8888\nEND:VCARD\nBEGIN:VCARD\nFN:Office landline\nTEL:04 333 4444\nEND:VCARD\n'

const shots = [
	{ name: 'chats', path: '/crm/whatsapp' },
	{ name: 'chats-jvc', path: '/crm/whatsapp', act: async (p) => { await p.getByRole('button', { name: /501 4422/ }).click() } },
	{ name: 'block', path: '/crm/whatsapp?tab=block' },
	{ name: 'block-import', path: '/crm/whatsapp?tab=block', act: async (p) => {
		await p.setInputFiles('input[type=file]', { name: 'contacts.vcf', mimeType: 'text/vcard', buffer: Buffer.from(vcf) })
	} },
	{ name: 'listings', path: '/crm/whatsapp?tab=listings' },
	{ name: 'connection', path: '/crm/whatsapp?tab=connection' }
]
const viewports = [['desktop', { width: 1440, height: 900 }], ['phone', { width: 390, height: 844 }]]
const browser = await chromium.launch()
for (const dark of [false, true]) {
	for (const [vp, viewport] of viewports) {
		for (const s of shots) {
			if (dark && vp === 'phone' && s.name !== 'chats') continue
			const ctx = await browser.newContext({ viewport, colorScheme: dark ? 'dark' : 'light' })
			const page = await ctx.newPage()
			const errors = []
			page.on('pageerror', (e) => errors.push(String(e)))
			await page.addInitScript((x) => localStorage.setItem('authentication', JSON.stringify(x)), session)
			if (dark) await page.addInitScript(() => localStorage.setItem('theme', 'dark'))
			await page.route('**/api/v1/auth/me', (r) => r.fulfill({ json: user }))
			await page.route('**/api/v1/crm/**', (r) => r.fulfill({ json: [] }))
			await page.route('**/api/v1/whatsapp/**', (r) => {
				const url = new URL(r.request().url())
				const p = url.pathname.replace(/^.*\/api\/v1\/whatsapp/, '')
				if (p === '/connection') return r.fulfill({ json: status })
				if (p === '/connection/contacts') {
					const only = url.searchParams.get('blocked') === 'true'
					const items = contacts.filter((c) => !only || c.blocked)
					return r.fulfill({ json: { items, total: items.length, limit: 100, offset: 0 } })
				}
				if (p === '/connections') return r.fulfill({ json: [connection] })
				if (p === '/notifications') return r.fulfill({ json: messages.t1.filter((m) => m.status === 'approval_required') })
				if (p === '/connections/conn-1/threads') return r.fulfill({ json: threads })
				if (p === '/connections/conn-1/listings') return r.fulfill({ json: [] })
				const m = p.match(/^\/threads\/(t\d)\/messages$/)
				if (m) return r.fulfill({ json: messages[m[1]] ?? [] })
				return r.fulfill({ status: 404, json: { detail: `unexpected ${p}` } })
			})
			await page.goto(`${baseUrl}${s.path}`)
			await page.waitForSelector('.wa', { timeout: 20000 })
			if (dark) await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
			await page.waitForTimeout(1500)
			if (s.act) { await s.act(page); await page.waitForTimeout(700) }
			const file = join(outDir, `${dark ? 'dark' : 'light'}-${vp}-${s.name}.png`)
			await page.screenshot({ path: file })
			const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
			console.log(file, overflow ? 'HORIZONTAL-OVERFLOW' : '', errors.join(' | '))
			await ctx.close()
		}
	}
}
await browser.close()
