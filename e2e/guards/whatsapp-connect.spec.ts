import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Page, Route } from '@playwright/test'
import { expect, test } from '../fixtures/guards'

// Optional: set WA_SHOTS_DIR to keep screenshots of the connect, contacts and status steps.
const shots = process.env.WA_SHOTS_DIR
async function shot(page: Page, name: string) {
	if (!shots) return
	mkdirSync(shots, { recursive: true })
	await page.screenshot({ path: join(shots, `${name}.png`), fullPage: false })
}

const iso = new Date().toISOString()
const emptyContacts = { total: 0, blocked: 0, sync_requested_at: null, synced_at: null }

function connectedStatus(overrides: Record<string, unknown> = {}) {
	return {
		state: 'connected',
		signup_configured: true,
		connection_id: 'conn-1',
		phone_number_id: 'phone-1',
		waba_id: 'waba-1',
		business_id: 'biz-1',
		display_phone_number: '+971 50 123 4567',
		display_name: 'Sara Properties',
		onboarding_type: 'whatsapp_business_app',
		automation_enabled: false,
		automation_active: false,
		automation_paused_reason: null,
		connected_at: iso,
		disconnected_at: null,
		last_account_event: null,
		quality_rating: 'GREEN',
		can_send_message: 'AVAILABLE',
		health_errors: [],
		payment_method_status: 'unknown',
		contacts: { ...emptyContacts, sync_requested_at: iso },
		...overrides
	}
}

const people = [
	['Ali Hassan', '971501110001', true],
	['Alia Noor', '971501110002', true],
	['Sara Khan', '971501110003', true],
	['Omar Farid', '971501110004', false],
	['Mum', '971501110005', true]
].map(([name, wa_id, saved], i) => ({
	id: `contact-${i + 1}`,
	wa_id,
	name,
	in_address_book: saved,
	blocked: false,
	blocked_at: null,
	updated_at: iso
}))

const fbSdk = `
window.FB = {
	init: function (options) { window.__fbInit = options; },
	login: function (callback, options) { window.__fbLogin = { callback: callback, options: options }; }
};
if (window.fbAsyncInit) window.fbAsyncInit();
`

test('an agent connects WhatsApp, blocks contacts, turns replies on and disconnects', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	await page.setViewportSize({ width: 1440, height: 900 })

	// Server state the mocked API keeps for this walk-through.
	let configured = false
	let status: ReturnType<typeof connectedStatus> | null = null
	const contacts = people.map((person) => ({ ...person }))
	const calls: { method: string; path: string; body: unknown }[] = []
	const unreachable: string[] = []

	await page.route('https://connect.facebook.net/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/javascript', body: fbSdk })
	)
	// Anything on the real CRM API means presentation mode is off here; keep the shell quiet.
	await page.route('**/api/v1/crm/**', (route) => route.fulfill({ json: [] }))
	await page.route('**/api/v1/whatsapp/**', async (route: Route) => {
		const request = route.request()
		const url = new URL(request.url())
		const path = url.pathname.replace('/api/v1/whatsapp', '')
		const method = request.method()
		const body = request.postData() ? request.postDataJSON() : undefined
		calls.push({ method, path, body })

		if (path === '/signup/config') {
			return route.fulfill({
				json: configured
					? {
							configured: true,
							missing: [],
							app_id: 'app-1',
							config_id: 'cfg-1',
							graph_api_version: 'v21.0',
							extras: {
								setup: {},
								featureType: 'whatsapp_business_app_onboarding',
								sessionInfoVersion: '3'
							},
							state: 'signed-state'
						}
					: {
							configured: false,
							missing: ['config_id'],
							app_id: 'app-1',
							config_id: null,
							graph_api_version: 'v21.0',
							extras: {},
							state: null
						}
			})
		}
		if (path === '/connection' && method === 'GET') {
			return status
				? route.fulfill({ json: status })
				: route.fulfill({ status: 404, json: { detail: 'No connected WhatsApp number.' } })
		}
		if (path === '/signup/complete') {
			status = connectedStatus()
			return route.fulfill({ json: status })
		}
		if (path === '/connection/contacts' && method === 'GET') {
			const search = (url.searchParams.get('search') ?? '').toLowerCase()
			const onlyBlocked = url.searchParams.get('blocked') === 'true'
			const items = contacts
				.filter(
					(c) =>
						!search || (c.name ?? '').toLowerCase().includes(search) || c.wa_id.includes(search)
				)
				.filter((c) => !onlyBlocked || c.blocked)
			return route.fulfill({ json: { items, total: items.length, limit: 100, offset: 0 } })
		}
		if (path === '/connection/contacts/blocked') {
			const ids: string[] = body.contact_ids ?? []
			for (const c of contacts) if (ids.includes(c.id)) c.blocked = body.blocked
			const blockedTotal = contacts.filter((c) => c.blocked).length
			status = connectedStatus({
				...status,
				contacts: { ...status!.contacts, total: contacts.length, blocked: blockedTotal }
			})
			return route.fulfill({ json: { updated: ids.length, blocked_total: blockedTotal } })
		}
		if (path === '/connection/automation') {
			status = { ...status!, automation_enabled: body.enabled, automation_active: body.enabled }
			return route.fulfill({ json: status })
		}
		if (path === '/connection/disconnect') {
			status = null
			return route.fulfill({
				json: connectedStatus({
					state: 'disconnected',
					automation_enabled: false,
					disconnected_at: iso,
					contacts: emptyContacts
				})
			})
		}
		// The current workspace also reads its empty conversations while connecting.
		if (method === 'GET' && ['/connections', '/notifications', '/connections/conn-1/threads'].includes(path)) return route.fulfill({ json: [] })
		unreachable.push(`${method} ${path}`)
		return route.fulfill({ status: 404, json: { detail: 'unexpected' } })
	})

	// 1. Meta setup is not finished yet: a calm message, no error and no button to press.
	await page.goto('/crm/whatsapp')
	await expect(page.getByRole('heading', { name: 'WhatsApp', exact: true })).toBeVisible()
	await expect(page.getByText('WhatsApp connection is being set up')).toBeVisible()
	await expect(page.getByRole('button', { name: 'Connect WhatsApp' })).toHaveCount(0)
	await expect(page.getByRole('alert')).toHaveCount(0)
	// What to prepare is readable at once; the reassurance sits in a collapsed section.
	await expect(page.getByText('Use the WhatsApp Business app.')).toBeVisible()
	await expect(page.getByText('Blocked contacts are never read')).toBeHidden()
	await page.getByText('Good to know', { exact: true }).click()
	await expect(page.getByText('Blocked contacts are never read')).toBeVisible()
	await expect(page.getByText('Personal messages are never stored.')).toBeVisible()
	await expect(page.getByText('1,000 free replies a month')).toBeVisible()

	// 2. Configured: the Connect button wakes up and loads Meta's SDK.
	configured = true
	await page.reload()
	const connect = page.getByRole('button', { name: 'Connect WhatsApp' })
	await expect(connect).toBeEnabled()
	await shot(page, '1-connect-step')
	await connect.click()
	await expect(page.getByRole('button', { name: 'Waiting for Meta…' })).toBeDisabled()
	const login = await page.evaluate(() => (window as any).__fbLogin.options)
	expect(login).toMatchObject({
		config_id: 'cfg-1',
		response_type: 'code',
		override_default_response_type: true
	})
	expect(login.extras).toMatchObject({
		featureType: 'whatsapp_business_app_onboarding',
		sessionInfoVersion: '3'
	})
	expect(await page.evaluate(() => (window as any).__fbInit)).toMatchObject({
		appId: 'app-1',
		version: 'v21.0'
	})

	// A message from some other origin is ignored; Meta's real finish message then the code complete it.
	await page.evaluate(() => {
		window.dispatchEvent(
			new MessageEvent('message', {
				origin: 'https://evil.example',
				data: JSON.stringify({
					type: 'WA_EMBEDDED_SIGNUP',
					event: 'FINISH',
					data: { phone_number_id: 'attacker', waba_id: 'attacker' }
				})
			})
		)
		window.dispatchEvent(
			new MessageEvent('message', {
				origin: 'https://www.facebook.com',
				data: JSON.stringify({
					type: 'WA_EMBEDDED_SIGNUP',
					event: 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING',
					data: { phone_number_id: 'phone-1', waba_id: 'waba-1', business_id: 'biz-1' }
				})
			})
		)
		;(window as any).__fbLogin.callback({ authResponse: { code: 'one-time-code' } })
	})

	// 3. Connected: the number shows, contacts are still syncing.
	await expect(page.getByText('+971 50 123 4567').first()).toBeVisible()
	await page.getByRole('tab', { name: /^Block list/ }).click()
	await expect(page.getByText('Syncing your contacts from WhatsApp')).toBeVisible()
	const complete = calls.find((c) => c.path === '/signup/complete')
	expect(complete?.body).toEqual({
		state: 'signed-state',
		code: 'one-time-code',
		phone_number_id: 'phone-1',
		waba_id: 'waba-1',
		business_id: 'biz-1',
		event: 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING'
	})
	// The Connection tab keeps the guarded automation controls beside its status.
	await page.getByRole('tab', { name: 'Connection', exact: true }).click()
	// While contacts are still arriving, replies cannot be switched on by accident.
	await expect(page.getByRole('button', { name: 'Turn on replies' })).toBeDisabled()

	// 4. Contacts arrive; the sync notice goes away on its own.
	await page.getByRole('tab', { name: /^Block list/ }).click()
	status = connectedStatus({
		contacts: { total: contacts.length, blocked: 0, sync_requested_at: iso, synced_at: iso }
	})
	await expect(page.getByText('Syncing your contacts from WhatsApp')).toHaveCount(0, {
		timeout: 15_000
	})
	await expect(page.getByText('Ali Hassan')).toBeVisible()
	await expect(page.getByText('5 contacts')).toBeVisible()

	// 5. Search narrows the list; both matches are blocked in one step.
	await page.getByRole('searchbox', { name: 'Search contacts' }).fill('Al')
	await expect(page.getByText('Sara Khan')).toHaveCount(0)
	await expect(page.getByText('2 contacts')).toBeVisible()
	await page.getByLabel('Select all shown').check()
	await expect(page.getByText('2 selected')).toBeVisible()
	await page.getByRole('button', { name: 'Block 2', exact: true }).click()
	await expect(page.getByText('Blocked 2 contacts.')).toBeVisible()
	await expect(page.getByText('2 blocked')).toBeVisible()
	const blockCall = calls.find((c) => c.path === '/connection/contacts/blocked')
	expect(blockCall?.body).toEqual({ contact_ids: ['contact-1', 'contact-2'], blocked: true })
	await shot(page, '2-contacts-step')

	// A number that is not in the list can be blocked too, and a bad entry is explained.
	await page.getByLabel('Block a number that is not in the list').fill('hello')
	await page.getByRole('button', { name: 'Block number' }).click()
	await expect(page.getByRole('alert').filter({ hasText: 'Check this entry: hello' })).toBeVisible()
	await page.getByLabel('Block a number that is not in the list').fill('+971 55 765 4321')
	await page.getByRole('button', { name: 'Block number' }).click()
	await expect
		.poll(() =>
			calls.some(
				(c) =>
					JSON.stringify(c.body) ===
					JSON.stringify({ phone_numbers: ['971557654321'], blocked: true })
			)
		)
		.toBe(true)

	// 6. Turn replies on.
	await page.getByRole('tab', { name: 'Connection', exact: true }).click()
	await page.getByRole('button', { name: 'Turn on replies' }).click()
	await expect(page.getByText('are being answered automatically')).toBeVisible()
	expect(calls.find((c) => c.path === '/connection/automation')?.body).toEqual({ enabled: true })
	await shot(page, '3-status-replies-on')

	// 7. Disconnect asks first, then removes the connection.
	await page.getByRole('button', { name: 'Disconnect WhatsApp' }).click()
	const dialog = page.getByRole('dialog')
	await expect(dialog).toContainText('permanently delete the contacts')
	await dialog.getByRole('button', { name: 'Keep connected' }).click()
	await expect(dialog).toHaveCount(0)
	expect(calls.some((c) => c.path === '/connection/disconnect')).toBe(false)
	await page.getByRole('button', { name: 'Disconnect WhatsApp' }).click()
	await page.getByRole('dialog').getByRole('button', { name: 'Disconnect WhatsApp' }).click()
	await expect(page.getByText('WhatsApp was disconnected')).toBeVisible()
	await expect(page.getByRole('button', { name: /Connect WhatsApp again/ })).toBeVisible()
	expect(unreachable).toEqual([])
})

test('cancelling in the Meta window leaves nothing connected and says so', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	await page.route('https://connect.facebook.net/**', (route) =>
		route.fulfill({ status: 200, contentType: 'application/javascript', body: fbSdk })
	)
	await page.route('**/api/v1/crm/**', (route) => route.fulfill({ json: [] }))
	await page.route('**/api/v1/whatsapp/**', (route) => {
		const path = new URL(route.request().url()).pathname
		if (path.endsWith('/connection'))
			return route.fulfill({ status: 404, json: { detail: 'none' } })
		return route.fulfill({
			json: {
				configured: true,
				missing: [],
				app_id: 'app-1',
				config_id: 'cfg-1',
				graph_api_version: 'v21.0',
				extras: {},
				state: 's'
			}
		})
	})
	// Phone width: the page must not scroll sideways.
	await page.setViewportSize({ width: 390, height: 844 })
	await page.goto('/crm/whatsapp')
	await expect(page.getByRole('button', { name: 'Connect WhatsApp' })).toBeEnabled()
	expect(
		await page.evaluate(() => {
			const root = document.querySelector('.wa') as HTMLElement
			return root.scrollWidth <= root.parentElement!.clientWidth
		})
	).toBe(true)
	await shot(page, '5-connect-step-phone')
	await page.getByRole('button', { name: 'Connect WhatsApp' }).click()
	await page.evaluate(() => {
		window.dispatchEvent(
			new MessageEvent('message', {
				origin: 'https://www.facebook.com',
				data: JSON.stringify({
					type: 'WA_EMBEDDED_SIGNUP',
					event: 'CANCEL',
					data: { current_step: 'PHONE_NUMBER' }
				})
			})
		)
	})
	await expect(page.getByRole('alert').filter({ hasText: 'nothing was connected' })).toBeVisible()
	await expect(page.getByRole('button', { name: 'Connect WhatsApp' })).toBeEnabled()
})

test('admin sees how many agents have connected WhatsApp', async ({ page, usePersona }) => {
	await usePersona('admin')
	await page.setViewportSize({ width: 1440, height: 900 })
	await page.route('**/api/v1/admin/whatsapp/connections', (route) =>
		route.fulfill({
			json: {
				total: 3,
				connected: 2,
				automation_on: 1,
				automation_paused: 1,
				items: [
					{
						connection_id: 'c1',
						user_id: 'u1',
						user_email: 'sara@agency.example',
						organization_id: 'o1',
						organization_name: 'Agency One',
						phone_number_id: 'p1',
						display_phone_number: '+971 50 123 4567',
						display_name: 'Sara Properties',
						status: 'connected',
						onboarding_type: 'whatsapp_business_app',
						automation_enabled: true,
						automation_active: true,
						automation_paused_reason: null,
						contacts_total: 412,
						contacts_blocked: 38,
						contacts_synced_at: iso,
						last_message_at: iso,
						connected_at: iso,
						disconnected_at: null,
						can_send_message: 'AVAILABLE'
					},
					{
						connection_id: 'c2',
						user_id: 'u2',
						user_email: 'omar@agency.example',
						organization_id: 'o1',
						organization_name: 'Agency One',
						phone_number_id: 'p2',
						display_phone_number: '+971 55 000 1111',
						display_name: null,
						status: 'connected',
						onboarding_type: 'whatsapp_business_app',
						automation_enabled: true,
						automation_active: false,
						automation_paused_reason: 'assistant_disabled',
						contacts_total: 0,
						contacts_blocked: 0,
						contacts_synced_at: null,
						last_message_at: null,
						connected_at: iso,
						disconnected_at: null,
						can_send_message: 'LIMITED'
					},
					{
						connection_id: 'c3',
						user_id: 'u3',
						user_email: 'lina@other.example',
						organization_id: 'o2',
						organization_name: 'Other Realty',
						phone_number_id: 'p3',
						display_phone_number: null,
						display_name: null,
						status: 'disconnected',
						onboarding_type: null,
						automation_enabled: false,
						automation_active: false,
						automation_paused_reason: null,
						contacts_total: 0,
						contacts_blocked: 0,
						contacts_synced_at: null,
						last_message_at: null,
						connected_at: iso,
						disconnected_at: iso,
						can_send_message: null
					}
				]
			}
		})
	)
	await page.goto('/admin/whatsapp')
	await expect(page.getByRole('heading', { name: 'WhatsApp connections' })).toBeVisible()
	await expect(page.getByText('Connected now').locator('xpath=following-sibling::dd')).toHaveText(
		'2'
	)
	await expect(
		page.getByText('Automatic replies on').locator('xpath=following-sibling::dd')
	).toHaveText('1')
	await expect(
		page.getByText('Automatic replies paused').locator('xpath=following-sibling::dd')
	).toHaveText('1')
	const pausedRow = page.getByRole('row').filter({ hasText: 'omar@agency.example' })
	await expect(pausedRow.getByText('Paused', { exact: true })).toBeVisible()
	await expect(pausedRow.getByText('Assistant off server-wide')).toBeVisible()
	await expect(page.getByRole('row').filter({ hasText: 'sara@agency.example' })).toContainText('On')
	await expect(page.getByText('sara@agency.example')).toBeVisible()
	await expect(page.getByText('Sending limited')).toBeVisible()
	await shot(page, '4-admin-connections')
})

test('a switched-on number that the server has paused says so instead of "On"', async ({
	page,
	usePersona
}) => {
	await usePersona('active-member')
	await page.route('**/api/v1/whatsapp/notifications**', route => route.fulfill({ json: [] }))
	await page.setViewportSize({ width: 1440, height: 900 })
	const contacts = people
	await page.route('**/api/v1/crm/**', (route) => route.fulfill({ json: [] }))
	await page.route('**/api/v1/whatsapp/connection**', (route) => {
		const path = new URL(route.request().url()).pathname.replace('/api/v1/whatsapp', '')
		if (path === '/connection') {
			return route.fulfill({
				json: connectedStatus({
					automation_enabled: true,
					automation_active: false,
					automation_paused_reason: 'assistant_disabled',
					contacts: { total: contacts.length, blocked: 1, sync_requested_at: iso, synced_at: iso }
				})
			})
		}
		return route.fulfill({
			json: path.endsWith('/contacts') ? { items: contacts, total: contacts.length } : []
		})
	})
	await page.goto('/crm/whatsapp?tab=connection')
	const card = page.getByRole('region', { name: 'Automatic replies' })
	await expect(card.getByText('Paused', { exact: true })).toBeVisible()
	await expect(
		card.getByText(
			'Automatic replies are paused by Vitevue. New messages are not answered or added to the inbox here for now, so keep replying in WhatsApp yourself.'
		)
	).toBeVisible()
	await expect(card.getByText('are being answered automatically')).toHaveCount(0)
	await expect(card.getByRole('button', { name: 'Turn off replies' })).toBeVisible()
	await card.scrollIntoViewIfNeeded()
	await shot(page, '5-status-replies-paused')
})
