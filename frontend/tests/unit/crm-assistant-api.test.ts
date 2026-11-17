import { afterEach, expect, it, vi } from 'vitest'
import { client } from '$lib/api/client'
import { assistant } from '$lib/crm/assistant/api'

afterEach(() => vi.restoreAllMocks())

it('requests subsequent stored history pages so older chats and messages remain reachable', async () => {
	const get = vi.spyOn(client, 'get').mockResolvedValue({})
	await assistant.listConversations(50, 50)
	expect(get).toHaveBeenLastCalledWith('/api/v1/crm/assistant/conversations?limit=50&offset=50')
	await assistant.getMessages(7, 200)
	expect(get).toHaveBeenLastCalledWith(
		'/api/v1/crm/assistant/conversations/7/messages?limit=200&offset=200'
	)
})
