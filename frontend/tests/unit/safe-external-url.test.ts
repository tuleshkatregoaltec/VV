import { describe, expect, it } from 'vitest'
import { safeExternalUrl } from '$lib/utils/safeExternalUrl'

describe('safeExternalUrl', () => {
	it.each([
		'https://www.propertyfinder.ae/en/plp/rent/x-1.html',
		'http://example.com/a?b=c#d'
	])('allows %s', (url) => {
		expect(safeExternalUrl(url)).toBe(url)
	})

	it.each([
		'javascript:alert(1)',
		'JaVaScRiPt:alert(1)',
		' javascript:alert(1)',
		'java\nscript:alert(1)',
		'data:text/html,<script>alert(1)</script>',
		'vbscript:msgbox(1)',
		'file:///etc/passwd',
		'//evil.example/path',
		'/relative/path',
		'',
		'not a url'
	])('rejects %j', (url) => {
		expect(safeExternalUrl(url)).toBeNull()
	})

	it('rejects missing values', () => {
		expect(safeExternalUrl(null)).toBeNull()
		expect(safeExternalUrl(undefined)).toBeNull()
	})
})
