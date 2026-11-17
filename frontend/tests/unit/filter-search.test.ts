import { describe, expect, it } from 'vitest'
import { searchFilterOptions } from '$lib/utils/filterSearch'

describe('transaction option search', () => {
	const options = [
		'All',
		'Dubai Marina',
		'Marina Gate - Tower 1',
		'Marina Gate - Tower 2',
		'Al Barsha',
		'23 Marina'
	]
	it('finds partial words in any order and ignores punctuation and excess spaces', () => {
		expect(searchFilterOptions(options, ' gate,   marina ')).toEqual([
			'Marina Gate - Tower 1',
			'Marina Gate - Tower 2'
		])
		expect(searchFilterOptions(options, 'DUBAI MAR')).toEqual(['Dubai Marina'])
	})
	it('tolerates a missing letter or transposition but only returns genuine options', () => {
		expect(searchFilterOptions(options, 'dubai marna')).toEqual(['Dubai Marina'])
		expect(searchFilterOptions(options, 'duabi marina')).toEqual(['Dubai Marina'])
		expect(searchFilterOptions(options, 'Atlantis')).toEqual([])
	})
	it('does not fuzzy-match numeric building identities or short words', () => {
		expect(searchFilterOptions(options, 'gate tower 1')).toEqual(['Marina Gate - Tower 1'])
		expect(searchFilterOptions(options, '24 marina')).toEqual([])
		expect(searchFilterOptions(['Al Barsha'], 'el barsha')).toEqual([])
	})
	it('ranks literal matches first and preserves original labels', () => {
		expect(searchFilterOptions(['Marina', 'Marna', 'Márina Heights'], 'marna')).toEqual([
			'Marna',
			'Marina',
			'Márina Heights'
		])
		expect(searchFilterOptions(options, '  ')).toEqual(options)
	})
})
