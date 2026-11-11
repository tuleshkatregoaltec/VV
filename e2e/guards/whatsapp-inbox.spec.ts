import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import type { Page } from '@playwright/test'
import { expect, test } from '../fixtures/guards'

// Optional: set WA_SHOTS_DIR to keep screenshots.
const shots = process.env.WA_SHOTS_DIR
async function shot(page: Page, name: string) {
	if (!shots) return
	mkdirSync(shots, { recursive: true })
	await page.screenshot({ path: join(shots, `${name}.png`), fullPage: false })
}

test('WhatsApp reviews require authentication', async ({ page, useAnonymous }) => {
	await useAnonymous()
	await page.goto('/dashboard/whatsapp')
	await expect(page).toHaveURL(/\/auth\?next=%2Fdashboard%2Fwhatsapp$/)
})

test('members load only their own scoped connections and see an empty inbox when unconnected', async ({
	page,
	usePersona
}) => {
	await usePersona('active-member')
	let requests = 0
	await page.route('**/api/v1/whatsapp/**', (route) => {
		requests += 1
		return route.fulfill({ json: [] })
	})
	await page.goto('/dashboard/whatsapp')
	await expect(
		page.getByText('No WhatsApp connections. Ask your administrator to connect a business number.')
	).toBeVisible()
	await expect(page.getByRole('heading', { name: 'Needs your approval (0)' })).toBeVisible()
	expect(requests).toBeGreaterThan(0)
	await expect(page.getByRole('button', { name: 'Approve reply' })).toHaveCount(0)
})

test('owner reviews only sensitive drafts, preserves revisions and explicitly resumes automation', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	const now = '2026-11-03T10:00:00Z'
	const connection = {
		id: 'number-1',
		phone_number_id: 'business-number',
		account_id: 'account-1',
		display_name: 'Property desk',
		enabled: true,
		automation_active: true,
		automation_paused_reason: null,
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	const thread = {
		id: 'thread-1',
		connection_id: connection.id,
		sender: '+971500000001',
		paused: true,
		opted_out: false,
		created_at: now,
		updated_at: now
	}
	const draft = {
		id: 'sensitive-message',
		thread_id: thread.id,
		content: 'Can you discount the Marina apartment?',
		sent_at: now,
		status: 'approval_required',
		reply: 'Let me check with the owner.',
		risk: 'sensitive',
		topic: 'negotiation',
		reason: 'Price negotiation needs human review',
		evidence_ids: [],
		revision: 1,
		send_after: null,
		notification_created_at: now,
		notification_seen_at: null,
		created_at: now,
		updated_at: now
	}
	const cancelDraft = {
		...draft,
		id: 'cancel-message',
		content: 'Please confirm this contract.',
		reply: 'I will review the contract.'
	}
	const routine = {
		...draft,
		id: 'routine-message',
		content: 'How many bedrooms?',
		status: 'accepted',
		reply: 'The apartment has two bedrooms.',
		notification_created_at: null
	}
	const calls: { action: string; body: Record<string, unknown> }[] = []
	const threadOffsets: number[] = []
	const firstThreadPage = Array.from({ length: 100 }, (_, index) => ({
		...thread,
		id: `older-thread-${index}`,
		sender: `Customer ${index}`
	}))
	let conflict = false
	await page.route('**/api/v1/whatsapp/**', async (route) => {
		const url = new URL(route.request().url())
		const path = url.pathname.replace('/api/v1/whatsapp', '')
		const method = route.request().method()
		if (method === 'GET') {
			if (path.endsWith('/listings')) return route.fulfill({ json: [] })
			if (path.endsWith('/threads')) {
				const offset = Number(url.searchParams.get('offset') ?? '0')
				threadOffsets.push(offset)
				return route.fulfill({ json: offset === 0 ? firstThreadPage : [thread] })
			}
			const json =
				path === '/connections'
					? [connection]
					: path === '/notifications'
						? [draft, cancelDraft].filter((item) => item.status === 'approval_required')
						: [draft, cancelDraft, routine]
			return route.fulfill({ json })
		}
		const body = route.request().postDataJSON() ?? {}
		calls.push({ action: path, body })
		if (path === '/connections/number-1') {
			connection.enabled = body.enabled
			return route.fulfill({ json: connection })
		}
		if (path.endsWith('/resume') || path.endsWith('/takeover')) {
			thread.paused = path.endsWith('/takeover')
			return route.fulfill({ json: thread })
		}
		const message = path.includes(cancelDraft.id) ? cancelDraft : draft
		if (body.expected_revision !== message.revision) {
			return route.fulfill({ status: 409, json: { detail: 'Draft revision has changed' } })
		}
		if (conflict) {
			conflict = false
			message.revision += 1
			message.reply = 'Updated by another review.'
			return route.fulfill({ status: 409, json: { detail: 'Draft revision has changed' } })
		}
		if (method === 'PATCH') message.reply = body.reply
		else message.status = path.endsWith('/cancel') ? 'cancelled' : 'approved'
		message.revision += 1
		return route.fulfill({ json: message })
	})
	await page.goto('/dashboard/whatsapp')
	const inbox = page.getByRole('region', { name: 'Approval inbox' })
	await expect(inbox.getByRole('heading', { name: 'Needs your approval (2)' })).toBeVisible()
	await expect(inbox.getByText(routine.content)).toHaveCount(0)
	await inbox.getByRole('button', { name: 'Open review' }).first().click()
	expect(threadOffsets).toContain(100)
	const review = page.getByRole('article').filter({ hasText: draft.content })
	const cancelled = page.getByRole('article').filter({ hasText: cancelDraft.content })
	await expect(
		page.getByText('Accepted by WhatsApp · delivery not confirmed', { exact: true })
	).toBeVisible()
	await expect(page.getByRole('button', { name: 'Resume automation', exact: true })).toBeVisible()
	await review
		.getByRole('textbox', { name: 'Reply draft' })
		.fill('I will confirm the price with the owner.')
	await expect(review.getByRole('button', { name: 'Approve reply' })).toBeDisabled()
	await review.getByRole('button', { name: 'Save draft' }).click()
	await expect(review.getByRole('button', { name: 'Approve reply' })).toBeEnabled()
	expect(calls.at(-1)).toEqual({
		action: '/messages/sensitive-message',
		body: { expected_revision: 1, reply: 'I will confirm the price with the owner.' }
	})
	await review.getByRole('button', { name: 'Approve reply' }).click()
	await expect(review.getByText('Approved · queued for sending')).toBeVisible()
	expect(calls.at(-1)).toEqual({
		action: '/messages/sensitive-message/approve',
		body: { expected_revision: 2 }
	})
	await expect(page.getByRole('button', { name: 'Resume automation', exact: true })).toBeVisible()
	await expect(inbox.getByRole('heading', { name: 'Needs your approval (1)' })).toBeVisible()
	conflict = true
	await cancelled.getByRole('button', { name: 'Approve reply' }).click()
	await expect(page.getByRole('alert')).toContainText('Draft revision has changed')
	await expect(cancelled.getByRole('textbox')).toHaveValue('Updated by another review.')
	await cancelled.getByRole('button', { name: 'Cancel draft' }).click()
	await expect(cancelled.getByText('Cancelled', { exact: true })).toBeVisible()
	expect(calls.at(-1)).toEqual({
		action: '/messages/cancel-message/cancel',
		body: { expected_revision: 2 }
	})
	await page.getByRole('button', { name: 'Resume automation', exact: true }).click()
	await expect(
		page.getByRole('button', { name: 'Take over conversation', exact: true })
	).toBeVisible()
	await page.getByRole('button', { name: 'Take over conversation', exact: true }).click()
	await expect(page.getByRole('button', { name: 'Resume automation', exact: true })).toBeVisible()
	await page.getByRole('switch', { name: 'Automatic replies' }).click()
	await expect(page.getByRole('switch', { name: 'Automatic replies' })).not.toBeChecked()
	draft.status = 'approval_required'
	await page.getByRole('button', { name: 'Refresh inbox' }).click()
	await expect(review.getByRole('button', { name: 'Approve reply' })).toBeDisabled()
	await page.getByRole('switch', { name: 'Automatic replies' }).click()
	thread.opted_out = true
	await page.getByRole('button', { name: 'Refresh inbox' }).click()
	await expect(
		page.getByText(
			'Customer opted out. They must send START in WhatsApp before automation can resume.'
		)
	).toBeVisible()
	await expect(review.getByRole('button', { name: 'Approve reply' })).toBeDisabled()
	await expect(page.getByRole('button', { name: 'Resume automation', exact: true })).toBeDisabled()
})

test('the Automatic replies switch says Paused, with the reason, when the server has replies paused', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	const now = '2026-11-03T10:00:00Z'
	const connection = {
		id: 'number-1',
		phone_number_id: 'business-number',
		account_id: 'account-1',
		display_name: 'Property desk',
		enabled: true,
		automation_active: false,
		automation_paused_reason: 'assistant_disabled',
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	const patches: unknown[] = []
	await page.route('**/api/v1/whatsapp/**', async (route) => {
		const path = new URL(route.request().url()).pathname.replace('/api/v1/whatsapp', '')
		if (route.request().method() === 'PATCH') {
			patches.push(route.request().postDataJSON())
			return route.fulfill({ json: connection })
		}
		return route.fulfill({ json: path === '/connections' ? [connection] : [] })
	})
	await page.goto('/dashboard/whatsapp')
	const toggle = page.getByRole('switch', { name: 'Automatic replies' })
	await expect(toggle).toHaveText('Automatic replies paused')
	await expect(toggle).toBeChecked()
	await expect(toggle).toBeEnabled()
	await expect(
		page.getByText(
			'Automatic replies are paused by Vitevue. New messages are not answered or added to the inbox here for now, so keep replying in WhatsApp yourself.'
		)
	).toBeVisible()
	await expect(page.getByText('Automatic replies on', { exact: true })).toHaveCount(0)
	await toggle.click()
	await expect.poll(() => patches).toEqual([{ enabled: false }])
})

test('a disconnected number says reconnect, not paused by Vitevue', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	const now = '2026-11-03T10:00:00Z'
	const connection = {
		id: 'number-1',
		phone_number_id: 'business-number',
		account_id: 'account-1',
		display_name: 'Property desk',
		enabled: true,
		status: 'disconnected',
		automation_active: false,
		automation_paused_reason: null,
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	await page.route('**/api/v1/whatsapp/**', async (route) => {
		const path = new URL(route.request().url()).pathname.replace('/api/v1/whatsapp', '')
		return route.fulfill({ json: path === '/connections' ? [connection] : [] })
	})
	await page.goto('/dashboard/whatsapp')
	await expect(page.getByRole('switch', { name: 'Automatic replies' })).toHaveText(
		'Automatic replies not running'
	)
	await expect(
		page.getByText(
			'This number is disconnected, so automatic replies are not running. Reconnect it to start them again.'
		)
	).toBeVisible()
	await expect(page.getByText(/paused by Vitevue/)).toHaveCount(0)
})

test('broker explicitly publishes, renews and revokes customer listings without exposing CRM', async ({
	page,
	usePersona
}) => {
	await usePersona('active-member')
	const now = new Date().toISOString()
	const connection = {
		id: 'number-public',
		phone_number_id: 'business-number',
		account_id: 'account-public',
		display_name: 'Property desk',
		enabled: true,
		automation_active: true,
		automation_paused_reason: null,
		market_data_enabled: false,
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	const listings: Record<string, unknown>[] = []
	const calls: { path: string; body: Record<string, unknown> }[] = []
	await page.route('**/api/v1/whatsapp/**', async (route) => {
		const path = new URL(route.request().url()).pathname.replace('/api/v1/whatsapp', '')
		const method = route.request().method()
		if (method === 'GET') {
			return route.fulfill({
				json: path === '/connections' ? [connection] : path.endsWith('/listings') ? listings : []
			})
		}
		const body = route.request().postDataJSON() ?? {}
		calls.push({ path, body })
		if (path === '/connections/number-public') {
			connection.market_data_enabled = body.market_data_enabled
			return route.fulfill({ json: connection })
		}
		if (path.endsWith('/revoke')) {
			expect(body.expected_revision).toBe(listings[0].revision)
			listings[0] = { ...listings[0], revoked_at: now, revision: Number(listings[0].revision) + 1 }
		} else if (method === 'PUT') {
			expect(body.expected_revision).toBe(listings[0].revision)
			listings[0] = { ...listings[0], ...body, revision: Number(listings[0].revision) + 1 }
		} else {
			listings.push({
				...body,
				id: 'listing-public',
				connection_id: connection.id,
				revision: 1,
				revoked_at: null,
				created_at: now,
				updated_at: now
			})
		}
		return route.fulfill({ json: listings[0] })
	})
	await page.goto('/dashboard/whatsapp')
	const publication = page.getByRole('region', { name: 'Customer information' })
	await expect(publication.getByText('No listings published for this number.')).toBeVisible()
	await expect(publication.getByRole('button', { name: 'Publish approved listing' })).toBeDisabled()
	await publication
		.getByRole('checkbox', {
			name: 'I have permission to share this number’s market summaries with customers.'
		})
		.check()
	await expect.poll(() => connection.market_data_enabled).toBe(true)
	await publication.getByLabel('Listing title').fill('Marina two bedroom apartment')
	await publication.getByLabel('Location', { exact: true }).fill('Dubai Marina')
	await publication.getByRole('combobox', { name: /Transaction/ }).selectOption('rent')
	await publication.getByLabel('Bedrooms (optional)').fill('2')
	await publication.getByLabel('Annual rent (AED)').fill('120000')
	await publication
		.getByLabel('Approval expires (your local time)')
		.fill(new Date(Date.now() + 86400000).toISOString().slice(0, 16))
	await publication
		.getByRole('checkbox', {
			name: 'I have verified these details and approve sharing them with customers.'
		})
		.check()
	await publication.getByRole('button', { name: 'Publish approved listing' }).click()
	await expect(publication.getByText('Marina two bedroom apartment', { exact: true })).toBeVisible()
	expect(calls.at(-1)?.body).toMatchObject({
		approved_for_customer: true,
		price_aed: 120000,
		transaction: 'rent'
	})
	expect(calls.at(-1)?.body).not.toHaveProperty('organization_id')
	expect(calls.at(-1)?.body).not.toHaveProperty('contact_id')
	await publication.getByRole('button', { name: 'Edit and renew' }).click()
	await expect(
		publication.getByRole('checkbox', {
			name: 'I have verified these details and approve sharing them with customers.'
		})
	).not.toBeChecked()
	await expect(publication.getByRole('button', { name: 'Publish approved update' })).toBeDisabled()
	await publication.getByLabel('Annual rent (AED)').fill('125000')
	await publication
		.getByRole('checkbox', {
			name: 'I have verified these details and approve sharing them with customers.'
		})
		.check()
	await publication.getByRole('button', { name: 'Publish approved update' }).click()
	await expect(publication.getByText('AED 125,000 per year', { exact: false })).toBeVisible()
	expect(calls.at(-1)?.body.expected_revision).toBe(1)
	await publication.getByRole('button', { name: 'Revoke', exact: true }).click()
	await expect(publication.getByRole('button', { name: 'Revoke', exact: true })).toBeDisabled()
	await expect
		.poll(() => calls.at(-1))
		.toEqual({
			path: '/connections/number-public/listings/listing-public/revoke',
			body: { expected_revision: 2 }
		})
})

test('the inbox shows why a message needs the agent, in words, and says when its text was not kept', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	await page.setViewportSize({ width: 1280, height: 900 })
	const now = '2026-11-03T10:00:00Z'
	const connection = {
		id: 'number-1',
		phone_number_id: 'business-number',
		account_id: 'account-1',
		display_name: 'Property desk',
		enabled: true,
		automation_active: true,
		automation_paused_reason: null,
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	const thread = {
		id: 'thread-1',
		connection_id: connection.id,
		sender: '+971500000001',
		paused: true,
		opted_out: false,
		created_at: now,
		updated_at: now
	}
	const base = {
		thread_id: thread.id,
		sent_at: now,
		status: 'approval_required',
		reply: null,
		risk: 'approval',
		topic: null,
		evidence_ids: [],
		revision: 1,
		send_after: null,
		notification_created_at: now,
		notification_seen_at: null,
		created_at: now,
		updated_at: now
	}
	const identity = {
		...base,
		id: 'identity',
		content: 'Am I talking to a bot?',
		reason: 'identity_question',
		handoff_summary: 'Asked whether they’re talking to a bot — reply yourself.'
	}
	const overLimit = {
		...base,
		id: 'over-limit',
		content: null,
		reason: 'Over today’s automatic-reply limit for this contact. Reply yourself.',
		handoff_summary:
			'Over today’s automatic-reply limit for this contact, so no reply was sent and the thread is paused. Its text was not kept: read it in WhatsApp and reply yourself.'
	}
	const unknown = {
		...base,
		id: 'unknown-code',
		content: 'Is it still available?',
		reason: 'draft_failed',
		handoff_summary: null
	}
	await page.route('**/api/v1/whatsapp/**', (route) => {
		const path = new URL(route.request().url()).pathname.replace('/api/v1/whatsapp', '')
		const json =
			path === '/connections'
				? [connection]
				: path === '/notifications'
					? [identity, overLimit, unknown]
					: path.endsWith('/threads')
						? [thread]
						: path.endsWith('/messages')
							? [identity, overLimit, unknown]
							: []
		return route.fulfill({ json })
	})
	await page.goto('/dashboard/whatsapp')
	const inbox = page.getByRole('region', { name: 'Approval inbox' })
	await expect(
		inbox.getByText('Asked whether they’re talking to a bot — reply yourself.')
	).toBeVisible()
	await expect(inbox.getByText('Message text not saved. Read it in WhatsApp.')).toBeVisible()
	await expect(inbox.getByText('Draft failed', { exact: true })).toBeVisible()
	await expect(inbox.getByText('Customer request')).toHaveCount(0)
	await expect(page.getByText(/identity_question|draft_failed/)).toHaveCount(0)
	await inbox.getByRole('button', { name: 'Open review' }).first().click()
	const review = page.getByRole('article').filter({ hasText: 'Am I talking to a bot?' })
	await expect(
		review.getByText('Asked whether they’re talking to a bot — reply yourself.')
	).toBeVisible()
	await expect(
		page
			.getByRole('article')
			.filter({ hasText: 'Message text not saved' })
			.getByText('Its text was not kept')
	).toBeVisible()
	await shot(page, '1-inbox-handoff')
})
