import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '$lib/api/client'
import { whatsappConnect } from '$lib/api/whatsapp-connect'

vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

afterEach(() => vi.restoreAllMocks())

describe('WhatsApp connection API', () => {
	it('reads the connection and treats 404 as not connected', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ state: 'connected' } as never)
		await whatsappConnect.status()
		expect(get).toHaveBeenCalledWith('/api/v1/whatsapp/connection')
		const { ApiError } = await import('$lib/api/client')
		get.mockRejectedValueOnce(new ApiError('none', 404))
		expect(await whatsappConnect.status()).toBeNull()
		get.mockRejectedValueOnce(new ApiError('boom', 500))
		await expect(whatsappConnect.status()).rejects.toThrow('boom')
	})

	it('posts the signup result exactly as Meta reported it', async () => {
		const post = vi.spyOn(client, 'post').mockResolvedValue({} as never)
		const body = {
			state: 's',
			code: 'c',
			phone_number_id: 'p',
			waba_id: 'w',
			business_id: 'b',
			event: 'FINISH'
		}
		await whatsappConnect.complete(body)
		expect(post).toHaveBeenCalledWith('/api/v1/whatsapp/signup/complete', body)
	})

	it('lists contacts with search, blocked filter and paging', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ items: [] } as never)
		await whatsappConnect.contacts({ search: 'Sara', blocked: true, limit: 100, offset: 200 })
		expect(get).toHaveBeenCalledWith(
			'/api/v1/whatsapp/connection/contacts?search=Sara&blocked=true&limit=100&offset=200'
		)
		await whatsappConnect.contacts({ limit: 50, offset: 0 })
		expect(get).toHaveBeenLastCalledWith('/api/v1/whatsapp/connection/contacts?limit=50&offset=0')
	})

	it('sets, clears and syncs through the documented endpoints', async () => {
		const put = vi.spyOn(client, 'put').mockResolvedValue({} as never)
		const patch = vi.spyOn(client, 'patch').mockResolvedValue({} as never)
		const post = vi.spyOn(client, 'post').mockResolvedValue({} as never)
		await whatsappConnect.setBlocked({ contact_ids: ['a'], blocked: true })
		expect(put).toHaveBeenCalledWith('/api/v1/whatsapp/connection/contacts/blocked', {
			contact_ids: ['a'],
			blocked: true
		})
		await whatsappConnect.setAutomation(true)
		expect(patch).toHaveBeenCalledWith('/api/v1/whatsapp/connection/automation', { enabled: true })
		await whatsappConnect.retrySync()
		expect(post).toHaveBeenCalledWith('/api/v1/whatsapp/connection/contacts/sync', undefined)
		await whatsappConnect.disconnect()
		expect(post).toHaveBeenLastCalledWith('/api/v1/whatsapp/connection/disconnect', undefined)
	})

	it('reads the admin connection list', async () => {
		const get = vi.spyOn(client, 'get').mockResolvedValue({ total: 0 } as never)
		await whatsappConnect.adminConnections()
		expect(get).toHaveBeenCalledWith('/api/v1/admin/whatsapp/connections')
	})
})
