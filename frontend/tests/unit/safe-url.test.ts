import { describe, expect, it } from 'vitest'
import { safeExternalHref } from '../../src/lib/utils/safeUrl'

describe('safeExternalHref allows only web links from backend data', () => {
	it('keeps http and https URLs', () => {
		expect(safeExternalHref('https://maps.google.com/?q=1,2')).toBe(
			'https://maps.google.com/?q=1,2'
		)
		expect(safeExternalHref('http://example.com/a.pdf')).toBe('http://example.com/a.pdf')
	})
	it.each([
		'javascript:alert(1)',
		'JaVaScRiPt:alert(1)',
		' javascript:alert(1)',
		'\tjava\nscript:alert(1)',
		'data:text/html,<script>alert(1)</script>',
		'vbscript:msgbox(1)',
		'file:///etc/passwd',
		'blob:https://app.example/1',
		'//evil.example/x',
		'/relative/path',
		'mailto:a@b.c',
		'',
		'https://',
		'https://user:pass@evil.example/'
	])('rejects %j', (value) => {
		expect(safeExternalHref(value)).toBeNull()
	})
	it('rejects non-strings', () => {
		expect(safeExternalHref(null)).toBeNull()
		expect(safeExternalHref(undefined)).toBeNull()
		expect(safeExternalHref(42)).toBeNull()
		expect(safeExternalHref({})).toBeNull()
	})
})
