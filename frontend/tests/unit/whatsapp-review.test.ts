import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { whatsapp } from '$lib/api/whatsapp'
import { whatsappKeys, whatsappQueries } from '$lib/queries/whatsapp'

const identity = vi.hoisted(() => ({
	data: null as null | { id: string; organization_id: string }
}))
vi.mock('$lib/stores/user.svelte', () => ({ currentUser: identity }))
vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

afterEach(() => {
	vi.restoreAllMocks()
	identity.data = null
})

describe('WhatsApp review controls', () => {
	it('scopes publication queries to the signed-in broker and selected connection', () => {
		expect(whatsappQueries.listings('number-one').enabled).toBe(false)
		identity.data = { id: 'broker', organization_id: 'agency' }
		const key = whatsappKeys.listings('number-one')
		expect(whatsappQueries.listings('number-one').enabled).toBe(true)
		expect(whatsappQueries.listings(null).enabled).toBe(false)
		expect(whatsappKeys.listings('number-two')).not.toEqual(key)
		identity.data = { id: 'other-broker', organization_id: 'agency' }
		expect(whatsappKeys.listings('number-one')).not.toEqual(key)
	})

	it('requires the reviewed publication revision when changing or revoking customer facts', async () => {
		const put = vi.spyOn(client, 'put').mockResolvedValue({} as never)
		const post = vi.spyOn(client, 'post').mockResolvedValue({} as never)
		const body = {
			title: 'Marina apartment',
			location: 'Dubai Marina',
			property_type: 'apartment' as const,
			transaction: 'rent' as const,
			bedrooms: 2,
			price_aed: 120000,
			area_sqft: null,
			availability: 'available' as const,
			expires_at: '2026-11-05T12:00:00Z',
			approved_for_customer: true as const,
			expected_revision: 4
		}
		await whatsapp.updateListing('number/a', 'listing/b', body)
		expect(put).toHaveBeenCalledWith(
			'/api/v1/whatsapp/connections/number%2Fa/listings/listing%2Fb',
			body
		)
		await whatsapp.revokeListing('number/a', 'listing/b', 4)
		expect(post).toHaveBeenCalledWith(
			'/api/v1/whatsapp/connections/number%2Fa/listings/listing%2Fb/revoke',
			{ expected_revision: 4 }
		)
	})

	it.each([
		['listings', () => whatsapp.listings('number/a'), '/connections/number%2Fa/listings'],
		['threads', () => whatsapp.threads('number/a'), '/connections/number%2Fa/threads'],
		['messages', () => whatsapp.messages('thread/a'), '/threads/thread%2Fa/messages'],
		['notifications', () => whatsapp.notifications(), '/notifications']
	] as const)('loads %s beyond the first 100 without duplicate rows', async (_name, load, path) => {
		const firstPage = Array.from({ length: 100 }, (_, index) => ({ id: `item-${index}` }))
		const target = { id: 'review-on-second-page' }
		const get = vi
			.spyOn(client, 'get')
			.mockResolvedValueOnce(firstPage)
			.mockResolvedValueOnce([firstPage[99], target])
		const rows = await load()
		expect(rows).toHaveLength(101)
		expect(rows).toContainEqual(target)
		expect(get).toHaveBeenNthCalledWith(1, `/api/v1/whatsapp${path}?limit=100&offset=0`)
		expect(get).toHaveBeenNthCalledWith(2, `/api/v1/whatsapp${path}?limit=100&offset=100`)
		expect(get).toHaveBeenCalledTimes(2)
	})

	it('does not present a partial inbox as complete when a later page fails', async () => {
		vi.spyOn(client, 'get')
			.mockResolvedValueOnce(Array.from({ length: 100 }, (_, index) => ({ id: `item-${index}` })))
			.mockRejectedValueOnce(new Error('Inbox unavailable'))
		await expect(whatsapp.notifications()).rejects.toThrow('Inbox unavailable')
	})

	it('sends the expected revision and safely encodes Meta message identifiers', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({} as never)
		await whatsapp.cancel('wamid.a/b+=', 3)
		expect(post).toHaveBeenCalledWith('/api/v1/whatsapp/messages/wamid.a%2Fb%2B%3D/cancel', {
			expected_revision: 3
		})
	})

	it('edits a draft without approving it', async () => {
		const patch = vi.spyOn(client, 'patch').mockResolvedValue({} as never)
		const post = vi.spyOn(client, 'post').mockResolvedValue({} as never)
		await whatsapp.edit('message', { expected_revision: 2, reply: 'Please confirm the property.' })
		expect(patch).toHaveBeenCalledWith('/api/v1/whatsapp/messages/message', {
			expected_revision: 2,
			reply: 'Please confirm the property.'
		})
		expect(post).not.toHaveBeenCalled()
	})

	it('keeps review notification caches separate across accounts and organizations', () => {
		expect(whatsappQueries.notifications().enabled).toBe(false)
		identity.data = { id: 'owner', organization_id: 'agency-one' }
		const first = whatsappKeys.notifications()
		identity.data = { id: 'owner', organization_id: 'agency-two' }
		expect(whatsappKeys.notifications()).not.toEqual(first)
		identity.data = { id: 'colleague', organization_id: 'agency-one' }
		expect(whatsappKeys.notifications()).not.toEqual(first)
	})

	it('polls the durable inbox without treating polling as an approval', async () => {
		identity.data = { id: 'owner', organization_id: 'agency' }
		const notifications = vi.spyOn(whatsapp, 'notifications').mockResolvedValue([])
		const approve = vi.spyOn(whatsapp, 'approve')
		const query = whatsappQueries.notifications()
		expect(query.enabled).toBe(true)
		expect(query.refetchInterval).toBe(2000)
		await query.queryFn()
		expect(notifications).toHaveBeenCalledOnce()
		expect(approve).not.toHaveBeenCalled()
	})
})
