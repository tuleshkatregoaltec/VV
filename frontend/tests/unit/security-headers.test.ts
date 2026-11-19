import { describe, expect, it } from 'vitest'
import { applySecurityHeaders } from '../../src/lib/security/headers'

describe('applySecurityHeaders', () => {
	it('sets the baseline hardening headers', () => {
		const headers = new Headers({ 'content-type': 'text/html' })
		applySecurityHeaders(headers)
		expect(headers.get('strict-transport-security')).toBe('max-age=31536000; includeSubDomains')
		expect(headers.get('x-frame-options')).toBe('DENY')
		expect(headers.get('referrer-policy')).toBe('strict-origin-when-cross-origin')
		expect(headers.get('x-content-type-options')).toBe('nosniff')
		expect(headers.get('permissions-policy')).toContain('camera=()')
		expect(headers.get('permissions-policy')).toContain('microphone=(self)')
		expect(headers.get('permissions-policy')).toContain('geolocation=()')
		expect(headers.get('content-type')).toBe('text/html')
	})
})
