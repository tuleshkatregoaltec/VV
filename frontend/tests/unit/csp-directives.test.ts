import { describe, expect, it } from 'vitest'
import { configuredOrigins, cspDirectives } from '../../csp-directives.js'

const d = cspDirectives as Record<string, string[] | true>

describe('content security policy', () => {
	it('blocks framing, plugins and base-tag hijacking', () => {
		expect(d['frame-ancestors']).toEqual(['none'])
		expect(d['object-src']).toEqual(['none'])
		expect(d['base-uri']).toEqual(['self'])
		expect(d['form-action']).toEqual(['self'])
	})

	it('never allows inline or eval script', () => {
		const scripts = d['script-src'] as string[]
		expect(scripts).not.toContain('unsafe-inline')
		expect(scripts).not.toContain('unsafe-eval')
		expect(scripts.some((s) => s === '*' || s === 'https:' || s === 'data:')).toBe(false)
	})

	it('allows the origins the app talks to', () => {
		const connect = d['connect-src'] as string[]
		expect(connect).toContain('https://api-pilot.vitevue.com')
		expect(connect).toContain('https://fxszmyazeonmxxeixzoh.supabase.co')
		expect(connect).toContain('https://basemaps.cartocdn.com')
		expect(d['script-src']).toContain('https://connect.facebook.net')
		expect(d['worker-src']).toContain('blob:')
	})

	it('allows the API and auth servers the environment points at, as origins only', () => {
		// Without this, local development (API on localhost, auth on a LAN host) cannot sign in.
		expect(
			configuredOrigins({
				PUBLIC_API_BASE_URL: 'http://localhost:8000',
				PUBLIC_AUTH_BASE_URL: 'http://192.168.1.25:9999/auth/v1'
			})
		).toEqual(['http://localhost:8000', 'http://192.168.1.25:9999'])
		expect(configuredOrigins({ PUBLIC_API_BASE_URL: 'not a url' })).toEqual([])
		expect(configuredOrigins({})).toEqual([])
	})
})
