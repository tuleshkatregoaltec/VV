import { describe, expect, it } from 'vitest'

import {
	buildBlockRequest,
	extractContactNumbers,
	parsePhoneNumbers,
	selectionAfterToggle,
	selectVisible
} from '$lib/whatsapp/blocklist'

describe('parsePhoneNumbers', () => {
	it('keeps digits only, whatever the separators', () => {
		expect(parsePhoneNumbers('+971 50 123 4567, 00447911123456\n(055) 765-4321')).toEqual({
			numbers: ['971501234567', '447911123456', '0557654321'],
			invalid: []
		})
	})

	it('drops duplicates and reports entries that cannot be phone numbers', () => {
		expect(parsePhoneNumbers('971501234567; +971501234567, 12, hello')).toEqual({
			numbers: ['971501234567'],
			invalid: ['12', 'hello']
		})
	})

	it('treats empty input as nothing to block', () => {
		expect(parsePhoneNumbers('  \n ')).toEqual({ numbers: [], invalid: [] })
	})
})

describe('selection helpers', () => {
	it('toggles one contact in and out without mutating the old set', () => {
		const empty = new Set<string>()
		const one = selectionAfterToggle(empty, 'a')
		expect([...one]).toEqual(['a'])
		expect(empty.size).toBe(0)
		expect(selectionAfterToggle(one, 'a').size).toBe(0)
	})

	it('selects every visible contact, or clears them when all are already selected', () => {
		const rows = [{ id: 'a' }, { id: 'b' }]
		const all = selectVisible(new Set(['x']), rows)
		expect([...all].sort()).toEqual(['a', 'b', 'x'])
		expect([...selectVisible(all, rows)].sort()).toEqual(['x'])
	})
})

describe('buildBlockRequest', () => {
	it('sends chosen contacts and typed numbers together', () => {
		expect(
			buildBlockRequest({ ids: new Set(['a', 'b']), numbers: ['971500000001'], blocked: true })
		).toEqual([{ contact_ids: ['a', 'b'], phone_numbers: ['971500000001'], blocked: true }])
	})

	it('omits an empty list', () => {
		expect(buildBlockRequest({ ids: new Set(['a']), numbers: [], blocked: false })).toEqual([
			{ contact_ids: ['a'], blocked: false }
		])
	})

	it('returns nothing when there is nothing to send', () => {
		expect(buildBlockRequest({ ids: new Set(), numbers: [], blocked: true })).toEqual([])
	})

	it('splits lists above 1000 into several requests', () => {
		const ids = new Set(Array.from({ length: 2300 }, (_, i) => `c${i}`))
		const requests = buildBlockRequest({ ids, numbers: [], blocked: true })
		expect(requests.map((r) => r.contact_ids?.length)).toEqual([1000, 1000, 300])
	})
})

describe('extractContactNumbers', () => {
	it('reads names and every number from a vCard export', () => {
		const vcf = [
			'BEGIN:VCARD',
			'VERSION:3.0',
			'FN:Mum',
			'TEL;TYPE=CELL:+971 50 111 2222',
			'END:VCARD',
			'BEGIN:VCARD',
			'FN:Office',
			'TEL;TYPE=WORK:04 333 4444',
			'TEL:00971 55 999 8888',
			'END:VCARD'
		].join('\r\n')
		expect(extractContactNumbers(vcf)).toEqual([
			{ name: 'Mum', number: '971501112222' },
			{ name: 'Office', number: '97143334444' },
			{ name: 'Office', number: '971559998888' }
		])
	})
	it('reads a Name,Phone spreadsheet and skips the header and duplicates', () => {
		const csv = 'Name,Phone\n"Ali Khan",+971 52 123 4567\nAli again,+971521234567\nNo number,n/a'
		expect(extractContactNumbers(csv)).toEqual([{ name: 'Ali Khan', number: '971521234567' }])
	})
	it('uses the chosen country code for local numbers', () => {
		expect(extractContactNumbers('0501234567', '91')).toEqual([
			{ name: null, number: '91501234567' }
		])
	})
})
