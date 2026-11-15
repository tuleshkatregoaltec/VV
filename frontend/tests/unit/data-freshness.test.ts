import { describe, expect, it } from 'vitest'
import {
	describeAge,
	freshnessOf,
	newestDate,
	newListingsLabel,
	STALE_AFTER_DAYS
} from '$lib/utils/dataFreshness'

const NOW = new Date('2026-11-15T09:00:00Z')

describe('data freshness', () => {
	it('formats the snapshot date in a fixed timezone so it never shifts a day', () => {
		expect(freshnessOf('2026-05-27T23:30:00Z', NOW)?.date).toBe('27 May 2026')
	})

	it('measures age against the supplied clock in whole days', () => {
		expect(freshnessOf('2026-05-27T08:00:00Z', NOW)?.days).toBe(172)
	})

	it('flags data older than the stale threshold and passes fresh data', () => {
		expect(freshnessOf('2026-05-27T08:00:00Z', NOW)?.stale).toBe(true)
		const fresh = new Date(NOW.getTime() - (STALE_AFTER_DAYS - 1) * 86_400_000).toISOString()
		expect(freshnessOf(fresh, NOW)?.stale).toBe(false)
	})

	it('returns null for missing or unparseable dates', () => {
		expect(freshnessOf(null, NOW)).toBeNull()
		expect(freshnessOf('not a date', NOW)).toBeNull()
	})

	it('never reports a negative age for a date slightly in the future', () => {
		expect(freshnessOf('2026-11-15T12:00:00Z', NOW)?.days).toBe(0)
	})

	it.each([
		[0, 'today'],
		[1, '1 day ago'],
		[12, '12 days ago'],
		[45, '6 weeks ago'],
		[172, '5 months ago'],
		[800, '2 years ago']
	])('describes %i days as "%s"', (days, label) => {
		expect(describeAge(days)).toBe(label)
	})

	it('finds the newest date and ignores blanks and invalid values', () => {
		expect(
			newestDate(['2026-07-01T00:00:00Z', null, 'junk', '2026-07-05T10:00:00Z', undefined])
		).toBe('2026-07-05T10:00:00.000Z')
		expect(newestDate([])).toBeNull()
	})

	it('labels the new-listings window as relative to the snapshot, not to today', () => {
		expect(newListingsLabel('2026-05-27T08:00:00Z')).toBe('Listed in the 30 days to 27 May 2026')
		expect(newListingsLabel(null)).toBe('Listed in the 30 days before capture')
	})
})
