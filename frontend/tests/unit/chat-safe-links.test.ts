import { describe, expect, it } from 'vitest'
import { safeChatHref } from '../../src/lib/chat/safeLinks'

const origin = 'https://app.example'
describe('assistant links protect private context from outbound tracking', () => {
	it('keeps navigation to application records', () => {
		expect(safeChatHref('/crm/leads/41', origin)).toBe('/crm/leads/41')
		expect(safeChatHref('https://app.example/chat?conversationId=5', origin)).toBe(
			'/chat?conversationId=5'
		)
	})
	it.each([
		'https://tracker.example/?phone=private',
		'//tracker.example/collect',
		'javascript:alert(1)',
		'data:text/html,private',
		'blob:https://app.example/private',
		'/\\tracker.example',
		'/api/v1/export?private=1',
		'/auth?next=https://tracker.example',
		'https:\n//tracker.example'
	])('removes unapproved destinations: %s', (href) => {
		expect(safeChatHref(href, origin)).toBeNull()
	})
})
