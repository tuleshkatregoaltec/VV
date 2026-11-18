import { describe, expect, it } from 'vitest'

import { ApiError } from '$lib/api/client'
import { errorText } from '$lib/crm/write'

/* A part the backend does not support yet must say so. It used to read "The server had a
   problem. Try again in a moment." (any 5xx), which sent agents retrying something that could
   never work (Move to Offer, 11 Nov 2026). */
describe('error text', () => {
	it('names a feature that is not available yet instead of blaming the server', () => {
		const e = new ApiError(
			"A changed language isn't available on the backend yet.",
			501,
			'not_supported'
		)
		expect(errorText(e)).toBe("A changed language isn't available on the backend yet.")
	})

	it('keeps the generic line for a real server error', () => {
		expect(errorText(new ApiError('Internal Server Error', 500))).toBe(
			'The server had a problem. Try again in a moment.'
		)
	})
})
