import { afterEach, describe, expect, it, vi } from 'vitest'

import { chat } from '$lib/api/chat'

vi.mock('$lib/api/auth', () => ({ get_access_token: async () => 'fixture-token' }))

afterEach(() => vi.unstubAllGlobals())

async function streamedUrl(assistant?: 'crm' | 'market') {
	const fetch = vi.fn().mockResolvedValue(new Response('data: {"type":"done"}\n\n'))
	vi.stubGlobal('fetch', fetch)
	await chat.sendMessage(7, 'hello', () => {}, assistant)
	await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
	return String(fetch.mock.calls[0][0])
}

describe('each chat product answers from its own endpoint', () => {
	it('the CRM Operations Assistant streams from the CRM endpoint by default', async () => {
		expect(await streamedUrl()).toMatch(/\/api\/v1\/chat\/conversations\/7\/messages\/stream$/)
		expect(await streamedUrl('crm')).toMatch(/\/api\/v1\/chat\/conversations\/7\/messages\/stream$/)
	})

	it('Market AI (/chat) streams from its own endpoint, never the CRM one', async () => {
		expect(await streamedUrl('market')).toMatch(
			/\/api\/v1\/market-chat\/conversations\/7\/messages\/stream$/
		)
	})
})
