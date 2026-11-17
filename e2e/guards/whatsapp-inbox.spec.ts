import type { Page } from '@playwright/test'
import { expect, test } from '../fixtures/guards'

const now = '2026-11-03T10:00:00Z'

function connectedStatus() {
	return {
		state: 'connected',
		signup_configured: true,
		connection_id: 'number-1',
		phone_number_id: 'business-number',
		waba_id: 'account-1',
		business_id: 'b1',
		display_phone_number: '+971 50 000 0000',
		display_name: 'Property desk',
		onboarding_type: 'env',
		automation_enabled: true,
		automation_active: true,
		automation_paused_reason: null,
		connected_at: now,
		disconnected_at: null,
		last_account_event: null,
		quality_rating: null,
		can_send_message: 'AVAILABLE',
		health_errors: [],
		payment_method_status: 'unknown',
		contacts: { total: 0, blocked: 0, sync_requested_at: null, synced_at: null }
	}
}

async function mockShell(page: Page) {
	await page.route('**/api/v1/crm/**', (route) => route.fulfill({ json: [] }))
}

test('WhatsApp requires authentication', async ({ page, useAnonymous }) => {
	await useAnonymous()
	await page.goto('/crm/whatsapp')
	await expect(page).toHaveURL(/\/auth\?next=%2Fcrm%2Fwhatsapp/)
})

test('owner reviews held replies in the chat, keeps revisions and hands chats back and forth', async ({
	page,
	usePersona
}) => {
	await usePersona('active-owner')
	await mockShell(page)
	const status = connectedStatus()
	const connection = {
		id: 'number-1',
		phone_number_id: 'business-number',
		account_id: 'account-1',
		display_name: 'Property desk',
		enabled: true,
		automation_active: true,
		automation_paused_reason: null,
		market_data_enabled: false,
		approved_knowledge: [],
		created_at: now,
		updated_at: now
	}
	const thread = {
		id: 'thread-1',
		connection_id: connection.id,
		sender: '971500000001',
		paused: true,
		opted_out: false,
		created_at: now,
		updated_at: now
	}
	const draft = {
		id: 'sensitive-message',
		thread_id: thread.id,
		content: 'Can you discount the Marina apartment?',
		sent_at: '2026-11-03T10:01:00Z',
		status: 'approval_required',
		reply: 'Let me check with the owner.',
		risk: 'sensitive',
		topic: 'negotiation',
		reason: 'Price negotiation needs human review',
		handoff_summary: 'Wants a discount on the Marina apartment.',
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
		sent_at: '2026-11-03T10:02:00Z',
		reply: 'I will review the contract.',
		handoff_summary: null
	}
	const routine = {
		...draft,
		id: 'routine-message',
		content: 'How many bedrooms?',
		sent_at: '2026-11-03T10:00:00Z',
		status: 'accepted',
		reply: 'The apartment has two bedrooms.',
		handoff_summary: null,
		notification_created_at: null
	}
	const calls: { action: string; body: Record<string, unknown> }[] = []
	const threadOffsets: number[] = []
	const olderThreads = Array.from({ length: 100 }, (_, index) => ({
		...thread,
		id: `older-thread-${index}`,
		sender: `97150000${String(index).padStart(4, '0')}`,
		paused: false,
		updated_at: '2026-11-01T10:00:00Z'
	}))
	let conflict = false
	await page.route('**/api/v1/whatsapp/**', async (route) => {
		const url = new URL(route.request().url())
		const path = url.pathname.replace(/^.*\/api\/v1\/whatsapp/, '')
		const method = route.request().method()
		if (method === 'GET') {
			if (path === '/connection') return route.fulfill({ json: status })
			if (path === '/connection/contacts')
				return route.fulfill({ json: { items: [], total: 0, limit: 100, offset: 0 } })
			if (path.endsWith('/listings')) return route.fulfill({ json: [] })
			if (path.endsWith('/threads')) {
				const offset = Number(url.searchParams.get('offset') ?? '0')
				threadOffsets.push(offset)
				return route.fulfill({ json: offset === 0 ? olderThreads : [thread] })
			}
			if (path === '/connections') return route.fulfill({ json: [connection] })
			if (path === '/notifications')
				return route.fulfill({
					json: [draft, cancelDraft].filter((item) => item.status === 'approval_required')
				})
			if (path === `/threads/${thread.id}/messages`)
				return route.fulfill({ json: [cancelDraft, draft, routine] })
			return route.fulfill({ json: [] })
		}
		const body = route.request().postDataJSON() ?? {}
		calls.push({ action: path, body })
		if (path === '/connection/contacts/blocked') {
			return route.fulfill({ json: { updated: 1, blocked_total: 1 } })
		}
		if (path === '/connection/automation') {
			status.automation_enabled = body.enabled
			status.automation_active = body.enabled
			return route.fulfill({ json: status })
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

	// The old review inbox address now opens the one WhatsApp page.
	await page.goto('/dashboard/whatsapp')
	await expect(page).toHaveURL(/\/crm\/whatsapp$/)
	await expect(page.getByRole('tab', { name: /Conversations/ })).toContainText('2')
	// Every page of conversations is read, and the one waiting for approval is listed first.
	const list = page.getByRole('complementary', { name: 'Conversations' })
	await expect(list.getByRole('button').first()).toContainText('+971 50 000 0001')
	expect(threadOffsets).toContain(100)
	await expect(list.getByRole('button').first()).toContainText('Needs your approval')

	const chat = page.getByRole('region', { name: 'Conversation' })
	await expect(chat.getByText(routine.reply)).toBeVisible()
	await expect(chat.getByText('Wants a discount on the Marina apartment.')).toBeVisible()
	await expect(chat.getByRole('button', { name: 'Let the assistant reply' })).toBeVisible()

	const held = chat.locator('[data-message="sensitive-message"]')
	await held.getByRole('button', { name: 'Edit' }).click()
	await held
		.getByRole('textbox', { name: 'Reply to send' })
		.fill('I will confirm the price with the owner.')
	await held.getByRole('button', { name: 'Save draft' }).click()
	await expect
		.poll(() => calls.at(-1))
		.toEqual({
			action: '/messages/sensitive-message',
			body: { expected_revision: 1, reply: 'I will confirm the price with the owner.' }
		})
	await expect(held).toContainText('I will confirm the price with the owner.')
	await held.getByRole('button', { name: 'Send reply' }).click()
	await expect
		.poll(() => calls.at(-1))
		.toEqual({
			action: '/messages/sensitive-message/approve',
			body: { expected_revision: 2 }
		})
	await expect(page.getByRole('tab', { name: /Conversations/ })).toContainText('1')

	conflict = true
	const other = chat.locator('[data-message="cancel-message"]')
	await other.getByRole('button', { name: 'Send reply' }).click()
	await expect(page.getByRole('alert')).toContainText('changed while you were looking')
	await expect(other).toContainText('Updated by another review.')
	await other.getByRole('button', { name: 'Discard' }).click()
	await expect
		.poll(() => calls.at(-1))
		.toEqual({
			action: '/messages/cancel-message/cancel',
			body: { expected_revision: 2 }
		})
	await expect(
		chat.locator('.ghosted').filter({ hasText: 'Updated by another review.' })
	).toBeVisible()

	await chat.getByRole('button', { name: 'Let the assistant reply' }).click()
	await expect(chat.getByRole('button', { name: 'I’ll handle this' })).toBeVisible()
	await chat.getByRole('button', { name: 'I’ll handle this' }).click()
	await expect(chat.getByRole('button', { name: 'Let the assistant reply' })).toBeVisible()

	await chat.getByRole('button', { name: 'Block +971 50 000 0001' }).click()
	await expect
		.poll(() => calls.at(-1))
		.toEqual({
			action: '/connection/contacts/blocked',
			body: { phone_numbers: ['971500000001'], blocked: true }
		})

	const replies = page.getByRole('switch', { name: /Automatic replies/ })
	await expect(replies).toHaveAttribute('aria-checked', 'true')
	await replies.click()
	await expect(replies).toHaveAttribute('aria-checked', 'false')
	await expect
		.poll(() => calls.at(-1))
		.toEqual({ action: '/connection/automation', body: { enabled: false } })
})
