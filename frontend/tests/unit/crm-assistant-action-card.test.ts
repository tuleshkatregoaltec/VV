import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '$lib/api/client'
import { createActionCard } from '$lib/crm/assistant/actionCard.svelte'
import type { ProposedAction } from '$lib/crm/assistant/stream'

// A proposed change runs only when the agent clicks Confirm, exactly once, and the CRM data is
// refreshed afterwards so the Leads page and sidebar counts show it.
const action: ProposedAction = {
	action_id: 'a1',
	action_type: 'status',
	lead_id: 7,
	summary: 'Move Ahmed Khan to qualified',
	before: { status: 'contacted' },
	after: { status: 'qualified' },
	status: 'pending'
}
const ok = (status: 'confirmed' | 'cancelled') => ({ action_id: 'a1', status, lead_id: 7 })

function setup(overrides: Partial<Parameters<typeof createActionCard>[1]> = {}) {
	const deps = {
		confirm: vi.fn(async () => ok('confirmed')),
		cancel: vi.fn(async () => ok('cancelled')),
		onConfirmed: vi.fn(),
		...overrides
	}
	return { card: createActionCard(action, deps), deps }
}

describe('assistant action card', () => {
	it('confirms once and refreshes the CRM', async () => {
		const { card, deps } = setup()
		await card.confirm()
		expect(card.state).toBe('confirmed')
		expect(deps.confirm).toHaveBeenCalledWith('a1')
		expect(deps.onConfirmed).toHaveBeenCalledTimes(1)
	})

	it('ignores a second click while the first is running', async () => {
		let release: (v: ReturnType<typeof ok>) => void = () => {}
		const { card, deps } = setup({
			confirm: vi.fn(() => new Promise<ReturnType<typeof ok>>((r) => (release = r)))
		})
		const first = card.confirm()
		expect(card.state).toBe('working')
		await card.confirm()
		await card.cancel()
		release(ok('confirmed'))
		await first
		expect(deps.confirm).toHaveBeenCalledTimes(1)
		expect(deps.cancel).not.toHaveBeenCalled()
	})

	it('shows an expired action as expired and changes nothing', async () => {
		const { card, deps } = setup({
			confirm: vi.fn(async () => {
				throw new ApiError('Action expired', 410)
			})
		})
		await card.confirm()
		expect(card.state).toBe('expired')
		expect(deps.onConfirmed).not.toHaveBeenCalled()
	})

	it('takes the final state from a 409 (confirmed in another tab)', async () => {
		const { card, deps } = setup({
			confirm: vi.fn(async () => {
				throw new ApiError('Action already confirmed', 409)
			})
		})
		await card.confirm()
		expect(card.state).toBe('confirmed')
		expect(deps.onConfirmed).toHaveBeenCalledTimes(1)
	})

	it('cancels', async () => {
		const { card, deps } = setup()
		await card.cancel()
		expect(card.state).toBe('cancelled')
		expect(deps.onConfirmed).not.toHaveBeenCalled()
	})

	it('shows the server reason when the lead is gone', async () => {
		const { card } = setup({
			confirm: vi.fn(async () => {
				throw new ApiError('Inbound enquiry not found', 404)
			})
		})
		await card.confirm()
		expect(card.state).toBe('error')
		expect(card.error).toBe('Inbound enquiry not found')
		// The agent can try again (the action is still pending on the server).
		expect(card.canAct).toBe(true)
	})

	it('starts in the stored state when the conversation is reloaded', () => {
		const card = createActionCard({ ...action, status: 'confirmed' }, setup().deps)
		expect(card.state).toBe('confirmed')
		expect(card.canAct).toBe(false)
	})

	it('keeps the confirm result (a draft link) for share cards', async () => {
		const { card } = setup({
			confirm: vi.fn(async () => ({
				...ok('confirmed'),
				href: 'https://wa.me/971501234567?text=Hi'
			}))
		})
		await card.confirm()
		expect(card.result?.href).toBe('https://wa.me/971501234567?text=Hi')
	})

	it("sends the agent's edited email with Send email", async () => {
		const { card, deps } = setup()
		await card.confirm({ subject: 'New subject', body: 'New message' })
		expect(deps.confirm).toHaveBeenCalledWith('a1', { subject: 'New subject', body: 'New message' })
		expect(card.state).toBe('confirmed')
	})
})
