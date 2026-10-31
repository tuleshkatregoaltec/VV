import { describe, expect, it } from 'vitest'
import {
	columnsRead,
	explainMatch,
	importCounts,
	MATCH_FILTERS,
	matchedSaleLine,
	matchOutcomeInfo,
	ownerMatchView
} from '$lib/crm/ownerImportReport'

/* The property-first matcher's results (docs/superpowers/plans/2026-10-29-owner-import-matching.md,
   "Live switch contract"): distinct units by tier, plus rows without a unit and lender rows. */
const OWNER_MATCH = {
	version: 'owner-match-2',
	rows: {
		matched_sale: 70,
		matched_sale_review: 10,
		property_confirmed_no_sale: 8,
		no_evidence: 7,
		lender: 5
	},
	units: { total: 80, confirmed: 52, review: 12, property_only: 6, not_matched: 10 },
	rows_without_unit: 9
}

describe('ownerMatchView', () => {
	it('gives each bucket its unit count and share of the distinct units', () => {
		const v = ownerMatchView(OWNER_MATCH)
		expect(v?.total).toBe(80)
		expect(v?.buckets.map((b) => [b.key, b.units, b.percent])).toEqual([
			['confirmed', 52, 65],
			['review', 12, 15],
			['property_only', 6, 8],
			['not_matched', 10, 13]
		])
	})

	it('puts the headline on confirmed units with the colour of each bucket', () => {
		const v = ownerMatchView(OWNER_MATCH)
		expect(v?.headline).toEqual({ units: 52, total: 80, percent: 65 })
		expect(v?.buckets.map((b) => b.tone)).toEqual(['green', 'amber', 'blue', 'neutral'])
	})

	it('reports rows without a unit identifier and lender rows excluded', () => {
		const v = ownerMatchView(OWNER_MATCH)
		expect(v?.rowsWithoutUnit).toBe(9)
		expect(v?.lenderRows).toBe(5)
	})

	it('sizes the stacked bar from the units, summing to the whole', () => {
		const v = ownerMatchView(OWNER_MATCH)
		const widths = v?.buckets.map((b) => b.units / (v?.total ?? 1)) ?? []
		expect(widths.reduce((a, b) => a + b, 0)).toBeCloseTo(1)
	})

	it('has a meaning for every bucket', () => {
		for (const b of ownerMatchView(OWNER_MATCH)?.buckets ?? [])
			expect(b.meaning.length).toBeGreaterThan(20)
	})

	it('is null while the re-match is pending (older import without owner_match)', () => {
		expect(ownerMatchView(undefined)).toBeNull()
		expect(ownerMatchView(null)).toBeNull()
	})

	it('shows zero percent, not NaN, for a file with no units', () => {
		const v = ownerMatchView({
			...OWNER_MATCH,
			units: { total: 0, confirmed: 0, review: 0, property_only: 0, not_matched: 0 }
		})
		expect(v?.headline.percent).toBe(0)
		expect(v?.buckets.every((b) => b.percent === 0)).toBe(true)
	})

	it('is read from the import summary by importCounts, and absent on old imports', () => {
		expect(
			importCounts({ total_rows: 5, owner_match: OWNER_MATCH }).ownerMatch?.headline.units
		).toBe(52)
		expect(importCounts({ total_rows: 5 }).ownerMatch).toBeNull()
	})
})

describe('MATCH_FILTERS', () => {
	it('filters by colour, and by outcome where a colour is shared (grey: not matched vs lender)', () => {
		expect(MATCH_FILTERS.map((f) => [f.id, f.colours, f.outcomes])).toEqual([
			['all', [], []],
			['confirmed', ['green'], []],
			['review', ['amber'], []],
			['property_only', ['blue'], []],
			['not_matched', [], ['rejected', 'no_evidence']],
			['lender', [], ['lender']]
		])
	})
})

describe('matchOutcomeInfo', () => {
	it('labels the outcome and takes its tone from the backend colour', () => {
		expect(matchOutcomeInfo('matched_sale', 'green')).toEqual({ label: 'Confirmed', tone: 'green' })
		expect(matchOutcomeInfo('matched_sale_review', 'amber')?.tone).toBe('amber')
		expect(matchOutcomeInfo('property_confirmed_no_sale', 'blue')?.label).toBe(
			'Property found, no sale'
		)
		expect(matchOutcomeInfo('rejected', 'red')?.label).toBe('Contradicted')
		expect(matchOutcomeInfo('no_evidence', 'grey')).toEqual({
			label: 'Not matched',
			tone: 'neutral'
		})
		expect(matchOutcomeInfo('lender', 'grey')?.label).toBe('Lender')
	})

	it('says how a green match was reached', () => {
		expect(matchOutcomeInfo('matched_sale_via_mortgage', 'green')?.label).toBe(
			'Confirmed via mortgage'
		)
		expect(matchOutcomeInfo('matched_sale_inferred_unit', 'green')?.label).toBe(
			'Confirmed, unit inferred'
		)
	})

	it('falls back to the colour for an outcome it does not know', () => {
		expect(matchOutcomeInfo('something_new', 'amber')).toEqual({
			label: 'Needs review',
			tone: 'amber'
		})
		expect(matchOutcomeInfo(undefined, undefined)).toBeNull()
	})
})

describe('explainMatch', () => {
	it.each([
		['unit differs', 'Transactions has this sale under another unit number'],
		['sheet_names_two_units', 'The sheet names two different units'],
		['sheet_names_two_villas', 'The sheet names two different villas'],
		['eliminated', 'Other units with a sale at this price were ruled out'],
		['size_basis_differs', "The sheet's size fits the sale on a different basis"],
		['share_sale', 'The sale was for a share of the unit'],
		[
			'share_qualifier_differs: DXBI sold 2807 (Q 1)',
			'Another share of this unit sold at this price'
		],
		['buildingno_renumbered', 'The sheet numbers the villas differently'],
		['learned_unit_alias', 'The unit number was learned from other rows in this file'],
		['financing_row', 'A mortgage or other financing row'],
		['no_amount', 'The row has no price'],
		['unit_not_in_dxbi', 'This unit is not in the Transactions data'],
		['ambiguous_unit', 'This unit number exists in several buildings; none sold at this price']
	])('translates %s', (code, start) => {
		expect(explainMatch(code)).toMatch(
			new RegExp(`^${start.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)
		)
	})

	it('keeps the detail the matcher printed after the code', () => {
		expect(explainMatch("unit differs: Transactions says 1203, sheet says ['1230']")).toBe(
			'Transactions has this sale under another unit number: it says 1203, the sheet says 1230.'
		)
		expect(explainMatch("sheet_names_two_units ['101', '102']: matched 102")).toBe(
			'The sheet names two different units (101, 102): matched 102.'
		)
		expect(explainMatch('unit 1203 exists in DXBI but has no sale within 2 AED')).toBe(
			'Unit 1203 is in the Transactions data, but no sale is within AED 2 of this price.'
		)
		expect(
			explainMatch('Transactions: 1 sale(s) fit place and size, 2 belong to other units')
		).toBe(
			'Transactions has 1 sale at this price for this place and size; 2 other sales belong to other units.'
		)
	})

	// The strings below are the matcher's own (backend/app/crm/owner_matcher.py, owner_match_status.py).
	it.each([
		[
			'unit 1410 sold on 2024-03-21',
			'A mortgage registered the same day the unit sold: the owner bought it with this mortgage.'
		],
		['size_conflict', 'The unit’s size doesn’t fit the sheet.'],
		['unit 1410 is 1,200 sqft', 'Unit 1410 is 1,200 sqft in Transactions.'],
		['ambiguous_unit', 'This unit number exists in several buildings; none sold at this price.'],
		["3 properties: [('A', '12'), ('B', '12')]", '3 properties have this unit number.'],
		['no_sale_at_price_and_size', 'No sale in the place fits this price and size.'],
		[
			'ambiguous_price_size',
			'Several properties in the place have a sale at this price and size, so none can be chosen.'
		],
		[
			'only property with a sale at this price and size in the place; size read as sqft',
			'The unit was inferred: it is the only property in the place with a sale at this price and size (size read as sqft).'
		],
		[
			'A bank or finance company on a financing row: the lender, not an owner.',
			'A bank or finance company on a mortgage row: the lender, not an owner.'
		]
	])('translates the backend string %s', (raw, plain) => {
		expect(explainMatch(raw)).toBe(plain)
	})

	it('falls back to the raw text for a code it does not know', () => {
		expect(explainMatch('brand_new_code 42')).toBe('brand_new_code 42')
		expect(explainMatch('  ')).toBe('')
	})
})

describe('matchedSaleLine', () => {
	it('reads unit, building, amount, date and source in one line', () => {
		expect(
			matchedSaleLine({
				unit: '1203',
				building: 'Burj Crown',
				project: 'Downtown',
				area: 'Downtown Dubai',
				amount_aed: 2_150_000,
				date: '2024-03-21',
				sqft: 1180,
				source: 'dxbi'
			})
		).toBe('1203 · Burj Crown · AED 2,150,000 · 21 Mar 2024')
	})

	it('skips what is missing and is empty without a sale', () => {
		expect(matchedSaleLine({ project: 'Downtown', amount_aed: 900_000 })).toBe(
			'Downtown · AED 900,000'
		)
		expect(matchedSaleLine(null)).toBe('')
	})
})

describe('columnsRead', () => {
	const sheet = {
		name: 'Owners',
		rows: 120,
		family: 'transaction_party',
		source: 'llm' as const,
		confidence: 0.8,
		fields: [
			{ field: 'contact_name', column: 'Owner Name' },
			{ field: 'unit_number', column: 'Flat' },
			{ field: 'transaction_price_aed', column: 'Price' }
		],
		warnings: [
			'Columns not imported: Remarks, Agent Code.',
			'Size has no stated unit; it cannot corroborate a transaction match.'
		],
		checks: []
	}

	it('names the field each column feeds', () => {
		expect(columnsRead(sheet).fields).toEqual([
			{ field: 'Owner name', column: 'Owner Name' },
			{ field: 'Unit number', column: 'Flat' },
			{ field: 'Sale price (AED)', column: 'Price' }
		])
	})

	it('lists unmapped columns as a warning, apart from other warnings', () => {
		const r = columnsRead(sheet)
		expect(r.notImported).toEqual(['Remarks', 'Agent Code'])
		expect(r.warnings).toEqual([
			'Size has no stated unit; it cannot corroborate a transaction match.'
		])
	})

	it.each(['llm', 'reused', 'override'] as const)('marks a %s mapping as auto-mapped', (source) => {
		expect(columnsRead({ ...sheet, source }).auto).toBe(true)
	})

	it.each([
		'heuristic',
		'heuristic_fallback'
	] as const)('does not mark a %s mapping as auto-mapped', (source) => {
		expect(columnsRead({ ...sheet, source }).auto).toBe(false)
	})

	it('explains where an auto-mapping came from', () => {
		expect(columnsRead(sheet).sourceNote).toMatch(/model/i)
		expect(columnsRead({ ...sheet, source: 'reused' }).sourceNote).toMatch(/earlier/i)
		expect(columnsRead({ ...sheet, source: 'override' }).sourceNote).toMatch(
			/set by hand|manual|chosen/i
		)
	})

	it('reports no unmapped columns when the warning is absent', () => {
		expect(columnsRead({ ...sheet, warnings: [] }).notImported).toEqual([])
	})

	it('carries the sheet-level mapping checks', () => {
		const checks = [
			{
				level: 'error' as const,
				code: 'no_name' as const,
				text: 'No name column: every row is dropped.'
			}
		]
		expect(columnsRead({ ...sheet, checks }).checks).toEqual(checks)
	})
})

describe('explainMatch wording for evidence lines', () => {
	it('hides type labels that name the same kind of property', () => {
		expect(explainMatch('type_label_differs (Flat vs Unit)')).toBe('')
		expect(explainMatch('type_label_differs (Building vs Villa)')).toBe('')
	})
	it('keeps a real type difference', () => {
		expect(explainMatch('type_label_differs (Land vs Villa)')).toBe(
			'The sheet says Land, Transactions says Villa.'
		)
	})
	it('explains Transactions and registry lines', () => {
		expect(
			explainMatch('Transactions: 1 sale(s) fit place and size, 0 belong to other units')
		).toBe('Transactions has 1 sale at this price for this place and size.')
		expect(
			explainMatch('Transactions: 1 sale(s) fit place and size, 2 belong to other units')
		).toBe(
			'Transactions has 1 sale at this price for this place and size; 2 other sales belong to other units.'
		)
		expect(explainMatch('dld_only Sell - Pre registration')).toBe(
			'A land-registry sale with no unit number (Sell - Pre registration).'
		)
		expect(explainMatch('matched Delayed Sell')).toBe('A recorded sale (Delayed Sell).')
	})
})
