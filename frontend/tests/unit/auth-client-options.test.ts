import { describe, expect, it } from 'vitest'
import { authClientHeaders } from '$lib/api/auth-client-options'

describe('authClientHeaders', () => {
	it('sends the publishable key as the apikey header when configured', () => {
		expect(authClientHeaders('sb_publishable_DUMMYTEST')).toEqual({
			apikey: 'sb_publishable_DUMMYTEST'
		})
	})

	it('sends no headers when the key is empty or missing', () => {
		expect(authClientHeaders('')).toBeUndefined()
		expect(authClientHeaders(undefined)).toBeUndefined()
		expect(authClientHeaders('   ')).toBeUndefined()
	})
})
