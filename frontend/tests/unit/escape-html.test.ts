import { describe, expect, it } from 'vitest'
import { escapeHtml } from '../../src/lib/utils/escapeHtml'

describe('escapeHtml neutralises data placed into popup markup', () => {
	it('escapes markup and quote characters', () => {
		expect(escapeHtml(`<img src=x onerror="a()">'&`)).toBe(
			'&lt;img src=x onerror=&quot;a()&quot;&gt;&#39;&amp;'
		)
	})
	it('renders null and undefined as empty text', () => {
		expect(escapeHtml(null)).toBe('')
		expect(escapeHtml(undefined)).toBe('')
	})
	it('stringifies numbers', () => {
		expect(escapeHtml(12)).toBe('12')
	})
})
