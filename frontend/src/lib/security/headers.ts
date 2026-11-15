/**
 * Response headers added to every page response by hooks.server.ts. The Content-Security-Policy
 * itself comes from `kit.csp` in svelte.config.js, because only SvelteKit can nonce its own
 * bootstrap script. static/_headers repeats the same non-CSP headers for static assets, which the
 * Cloudflare Pages Worker does not serve.
 */
export const SECURITY_HEADERS: Readonly<Record<string, string>> = {
	'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
	'X-Content-Type-Options': 'nosniff',
	'X-Frame-Options': 'DENY',
	'Referrer-Policy': 'strict-origin-when-cross-origin',
	// Nothing in the app uses these features; denying them stops injected code from asking.
	'Permissions-Policy': [
		'accelerometer=()',
		'autoplay=()',
		'bluetooth=()',
		'camera=()',
		'display-capture=()',
		'geolocation=()',
		'gyroscope=()',
		'hid=()',
		'magnetometer=()',
		'microphone=()',
		'midi=()',
		'payment=()',
		'serial=()',
		'usb=()',
		'xr-spatial-tracking=()'
	].join(', ')
}

export function applySecurityHeaders(headers: Headers): void {
	for (const [name, value] of Object.entries(SECURITY_HEADERS)) headers.set(name, value)
}
