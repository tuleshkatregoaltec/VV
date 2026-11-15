import { describe, expect, it } from 'vitest'
import { cspDirectives } from '../../csp-directives.js'

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
})
