import type { Handle } from '@sveltejs/kit'
import { applySecurityHeaders } from '$lib/security/headers'

export const handle: Handle = async ({ event, resolve }) => {
	const response = await resolve(event)
	// Redirect and asset responses can carry immutable headers, so copy before changing.
	const headers = new Headers(response.headers)
	applySecurityHeaders(headers)
	return new Response(response.body, {
		status: response.status,
		statusText: response.statusText,
		headers
	})
}
