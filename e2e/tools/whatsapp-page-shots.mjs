// Renders /crm/whatsapp in every state with a mocked API and saves PNG screenshots.
//   node e2e/tools/whatsapp-page-shots.mjs <label> <outDir> [baseUrl]   (WA_DARK=1 for dark mode)
// Tall viewports on purpose: the CRM scrolls inside its shell, so this captures the whole page.
// Needs a running frontend dev server (default http://127.0.0.1:5199).
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { chromium } from '@playwright/test'

const [label = 'after', outDir = '.', baseUrl = 'http://127.0.0.1:5199'] = process.argv.slice(2)
mkdirSync(outDir, { recursive: true })
const iso = '2026-11-06T09:00:00Z'

const user = {
	id: 'user-1', email: 'kian@example.com', first_name: 'Kian', last_name: 'Agent',
	organization_id: 'org-1', organization_name: 'Acme', role: 'owner', is_owner: true,
	subscription_status: 'active'
}
const session = {
	access_token: 'mock', token_type: 'bearer', expires_in: 3600,
	expires_at: Math.floor(Date.now() / 1000) + 3600, refresh_token: 'mock',
	user: { id: 'user-1', aud: '', role: 'user', email: user.email, app_metadata: {}, user_metadata: {}, identities: [], created_at: iso }
}
const fbSdk = `window.FB={init:function(o){window.__fbInit=o},login:function(cb,o){window.__fbLogin={callback:cb,options:o}}};if(window.fbAsyncInit)window.fbAsyncInit();`

const names = ['Ali Hassan', 'Alia Noor', 'Sara Khan', 'Omar Farid', 'Mum', 'Dad', 'Layla Mansour', 'Yusuf Ibrahim']
const people = names.map((name, i) => ({
	id: `c${i + 1}`, wa_id: `97150111000${i + 1}`, name: i === 7 ? null : name, in_address_book: i !== 3,
	blocked: i === 4 || i === 5, blocked_at: null, updated_at: iso
}))
const synced = { total: 8, blocked: 2, sync_requested_at: iso, synced_at: iso }
const syncing = { total: 0, blocked: 0, sync_requested_at: iso, synced_at: null }
const base = (o = {}) => ({
	state: 'connected', signup_configured: true, connection_id: 'conn-1', phone_number_id: 'p1', waba_id: 'w1',
	business_id: 'b1', display_phone_number: '+971 50 123 4567', display_name: 'Kian Properties',
	onboarding_type: 'whatsapp_business_app', automation_enabled: false, automation_active: false,
	automation_paused_reason: null, connected_at: iso, disconnected_at: null, last_account_event: null,
	quality_rating: 'GREEN', can_send_message: 'AVAILABLE', health_errors: [], payment_method_status: 'unknown',
	contacts: synced, ...o
})

// status: null => 404 (nothing connected)
const scenarios = [
	{ name: '01-not-set-up', configured: false, status: null },
	{ name: '02-not-connected', configured: true, status: null },
	{ name: '03-connecting', configured: true, status: null, act: async (p) => { await p.getByRole('button', { name: /^Connect WhatsApp/ }).click() } },
	{ name: '04-connect-error', configured: true, status: null, act: async (p) => {
		await p.getByRole('button', { name: /^Connect WhatsApp/ }).click()
		await p.evaluate(() => window.dispatchEvent(new MessageEvent('message', { origin: 'https://www.facebook.com', data: JSON.stringify({ type: 'WA_EMBEDDED_SIGNUP', event: 'CANCEL', data: { current_step: 'PHONE_NUMBER' } }) })))
	} },
	{ name: '05-connected-syncing', configured: true, status: base({ contacts: syncing }), contacts: [] },
	{ name: '06-connected-replies-off', configured: true, status: base() },
	{ name: '07-connected-replies-on', configured: true, status: base({ automation_enabled: true, automation_active: true }) },
	{ name: '08-paused-assistant-disabled', configured: true, status: base({ automation_enabled: true, automation_paused_reason: 'assistant_disabled' }) },
	{ name: '09-paused-intake-disabled', configured: true, status: base({ automation_enabled: true, automation_paused_reason: 'intake_disabled' }) },
	{ name: '10-connected-limited', configured: true, status: base({ automation_enabled: true, automation_active: true, can_send_message: 'LIMITED', quality_rating: 'YELLOW', health_errors: ['Display name is pending review.'] }) },
	{ name: '11-disconnected', configured: true, status: base(), act: async (p) => {
		await p.getByRole('button', { name: 'Disconnect WhatsApp' }).click()
		await p.getByRole('dialog').getByRole('button', { name: 'Disconnect WhatsApp' }).click()
		await p.getByText('WhatsApp was disconnected').waitFor()
	}, onDisconnect: true }
]

const viewports = [['desktop', { width: 1280, height: 1500 }], ['phone', { width: 390, height: 2300 }]]
const browser = await chromium.launch()
for (const [vpName, viewport] of viewports) {
	for (const sc of scenarios) {
		const ctx = await browser.newContext({ viewport })
		const page = await ctx.newPage()
		let status = sc.status
		await page.addInitScript((s) => localStorage.setItem('authentication', JSON.stringify(s)), session)
		await page.route('**/api/v1/auth/me', (r) => r.fulfill({ json: user }))
		await page.route('https://connect.facebook.net/**', (r) => r.fulfill({ status: 200, contentType: 'application/javascript', body: fbSdk }))
		await page.route('**/api/v1/crm/**', (r) => r.fulfill({ json: [] }))
		await page.route('**/api/v1/whatsapp/**', (r) => {
			const url = new URL(r.request().url())
			const path = url.pathname.replace(/^.*\/api\/v1\/whatsapp/, '')
			if (path === '/signup/config')
				return r.fulfill({ json: sc.configured
					? { configured: true, missing: [], app_id: 'a', config_id: 'c', graph_api_version: 'v21.0', extras: {}, state: 's' }
					: { configured: false, missing: ['config_id'], app_id: 'a', config_id: null, graph_api_version: 'v21.0', extras: {}, state: null } })
			if (path === '/connection' && r.request().method() === 'GET')
				return status ? r.fulfill({ json: status }) : r.fulfill({ status: 404, json: { detail: 'none' } })
			if (path === '/connection/contacts') {
				const q = (url.searchParams.get('search') ?? '').toLowerCase()
				const only = url.searchParams.get('blocked') === 'true'
				const items = (sc.contacts ?? people).filter((c) => (!q || (c.name ?? '').toLowerCase().includes(q)) && (!only || c.blocked))
				return r.fulfill({ json: { items, total: items.length, limit: 100, offset: 0 } })
			}
			if (path === '/connection/disconnect') {
				status = null
				return r.fulfill({ json: base({ state: 'disconnected', automation_enabled: false, disconnected_at: iso, contacts: syncing }) })
			}
			return r.fulfill({ status: 404, json: { detail: 'unexpected' } })
		})
		await page.goto(`${baseUrl}/crm/whatsapp`)
		await page.waitForSelector('.wa', { timeout: 20000 })
		if (process.env.WA_DARK) await page.evaluate(() => { document.documentElement.dataset.theme = 'dark' })
		await page.waitForTimeout(sc.configured ? 1200 : 600)
		if (sc.act) { await sc.act(page); await page.waitForTimeout(500) }
		await page.screenshot({ path: join(outDir, `${label}-${sc.name}-${vpName}.png`), fullPage: true })
		const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)
		console.log(`${label} ${sc.name} ${vpName}${overflow ? ' HORIZONTAL-OVERFLOW' : ''}`)
		await ctx.close()
	}
}
await browser.close()
