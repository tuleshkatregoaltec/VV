import { describe, expect, it } from 'vitest'
import { formatAed, relativeTime } from '$lib/collections/publicFormat'

describe('public collection formatting', () => {
	it('formats sale and rent prices', () => {
		expect(formatAed(2500000, null)).toBe('AED 2,500,000')
		expect(formatAed(95000, 'yearly')).toBe('AED 95,000 / year')
	})

	it('returns empty string without a price', () => {
		expect(formatAed(null, null)).toBe('')
		expect(formatAed(undefined, 'yearly')).toBe('')
	})

	it('formats relative times', () => {
		const now = new Date('2026-11-12T12:00:00Z')
		expect(relativeTime('2026-11-12T11:59:40Z', now)).toBe('just now')
		expect(relativeTime('2026-11-12T09:00:00Z', now)).toBe('3 hours ago')
		expect(relativeTime('2026-11-10T12:00:00Z', now)).toBe('2 days ago')
		expect(relativeTime('2026-11-12T11:00:00Z', now)).toBe('1 hour ago')
	})
})
