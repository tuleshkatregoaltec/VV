/**
 * Owner import report: the counts and mapping checks a manager reads after an upload. Pure
 * functions over what /contact-imports returns (summary + sheet mappings); no fetching.
 * The checks follow the backend's own rules in backend/app/crm/import_parsing.py.
 */
import type { CrmContactImportSummary, CrmSheetMapping } from '$lib/api/generated/hey-api/types.gen'
import type { ImportSheet, MatchColour, MatchedSale, OwnerMatchSummary, Tone } from './api/types'
import { aed, fmt, fullDate } from './format'

export type ClaimStatus =
	| 'verified_current_owner'
	| 'probable_current_owner'
	| 'unit_linked_unverified'
	| 'former_owner'
	| 'unverified_former_owner'
	| 'conflicting_claim'
	| 'insufficient_property_data'
	| 'registry_not_observed'
	| 'unmatched'

/** No DLD property could be found for the row. */
export const FAILED_STATUSES: ClaimStatus[] = [
	'insufficient_property_data',
	'registry_not_observed',
	'unmatched'
]

export const STATUS_INFO: Record<ClaimStatus, { label: string; meaning: string; tone: Tone }> = {
	verified_current_owner: {
		label: 'Current owner',
		meaning: 'Matches the latest sale of the unit',
		tone: 'green'
	},
	probable_current_owner: {
		label: 'Possible current owner',
		meaning: 'Fits the latest sale, with a gap to check',
		tone: 'amber'
	},
	unit_linked_unverified: {
		label: 'Property found, owner unknown',
		meaning: 'The unit is identified, no sale ties the person to it',
		tone: 'amber'
	},
	former_owner: {
		label: 'Former owner',
		meaning: 'A matched sale shows a past owner',
		tone: 'neutral'
	},
	unverified_former_owner: {
		label: 'Seller to check',
		meaning: 'The file names a seller that no sale supports',
		tone: 'amber'
	},
	conflicting_claim: {
		label: 'Conflicting records',
		meaning: 'Sale records disagree with the file',
		tone: 'red'
	},
	insufficient_property_data: {
		label: 'Property not identified',
		meaning: 'No single property could be found for the row',
		tone: 'red'
	},
	registry_not_observed: {
		label: 'No sale found',
		meaning: 'The unit has no sale on record',
		tone: 'red'
	},
	unmatched: {
		label: 'Unmatched',
		meaning: 'No property or ownership change could be confirmed',
		tone: 'amber'
	}
}

/** What each status means and what to do about it, for the ⓘ on the import report's status tiles. */
export const STATUS_HELP: Record<ClaimStatus, { how: string; todo: string }> = {
	verified_current_owner: {
		how: 'The property, date and amount match a recorded sale, and no later sale is on record.',
		todo: 'Strong match. A transfer that is not on record would not show here.'
	},
	probable_current_owner: {
		how: 'The latest sale supports this person, but a date gap, a missing size unit or a seller role weakens the match.',
		todo: 'Likely the owner. Check before relying on it.'
	},
	unit_linked_unverified: {
		how: 'A unit, lease or plot was linked. A mortgage, gift or owner list alone does not show a sale.',
		todo: 'Check ownership another way.'
	},
	former_owner: {
		how: 'A sale in the file matches a recorded sale, and a later sale shows the unit changed hands.',
		todo: 'Treat as a past owner.'
	},
	unverified_former_owner: {
		how: 'The file names this person as seller, but no recorded sale supports it.',
		todo: 'Check the original row and the sale documents.'
	},
	conflicting_claim: {
		how: 'The file and the records disagree on the property, its type, the sale date or the amount, or several sales fit.',
		todo: 'Read the row’s reason and resolve the conflict before treating this as current ownership.'
	},
	insufficient_property_data: {
		how: 'The identifiers and the location, date and amount did not point to one property.',
		todo: 'Review the building, land and unit details in the file. Do not guess a unit.'
	},
	registry_not_observed: {
		how: 'The row has a unit, but no sale of it is on record.',
		todo: 'Check the unit number and building name.'
	},
	unmatched: {
		how: 'The property did not resolve to one unit, or the row is not an ownership change.',
		todo: 'Review the identifiers, location and event type, then correct the file.'
	}
}

/** The summary's count fields (it also holds a per-reason map and a flag). */
type SummaryCount = {
	[K in keyof CrmContactImportSummary]-?: CrmContactImportSummary[K] extends number | undefined
		? K
		: never
}[keyof CrmContactImportSummary]

const SUMMARY_KEY: Record<ClaimStatus, SummaryCount> = {
	verified_current_owner: 'verified_current_owners',
	probable_current_owner: 'probable_current_owners',
	unit_linked_unverified: 'unit_linked_unverified',
	former_owner: 'former_owners',
	unverified_former_owner: 'unverified_former_owners',
	conflicting_claim: 'conflicting_claims',
	insufficient_property_data: 'insufficient_property_data',
	registry_not_observed: 'registry_not_observed',
	unmatched: 'unmatched'
}

export interface ImportCounts {
	/** The property-first matcher's unit counts; null on imports made before it (re-match pending). */
	ownerMatch: OwnerMatchView | null
	rows: number
	kept: number
	/** Distinct units, villas or plots among the kept rows; null for imports made before it. */
	properties: number | null
	sourceProperties: CrmContactImportSummary['source_property_counts']
	salesHistoryRows: number | null
	plotOnlyRows: number | null
	merged: number
	dropped: number
	/** Rows with explicit registry property evidence; null for older summaries. */
	matched: number | null
	failed: number
	validContacts: number
	/** Contactable verified/probable candidates with a linked rental opportunity; not verified readiness. */
	readyToContact: number
	rentalLeads: number
	/** Property-linked rows ÷ kept; null when the metric or denominator is unavailable. */
	matchRate: number | null
	/** Property-linked rows ÷ original source rows. */
	sourceMatchRate: number | null
	byStatus: Record<ClaimStatus, number>
	/** Dropped rows per reason; empty for imports made before the dropped-rows log. */
	droppedByReason: Partial<Record<DropReason, number>>
	/** Whether the dropped rows can be listed (the log was saved at upload). */
	droppedLog: boolean
}

export function importCounts(summary: CrmContactImportSummary): ImportCounts {
	const n = (key: SummaryCount) => summary[key] ?? 0
	const byStatus = Object.fromEntries(
		(Object.keys(SUMMARY_KEY) as ClaimStatus[]).map((s) => [s, n(SUMMARY_KEY[s])])
	) as Record<ClaimStatus, number>
	const sum = (list: ClaimStatus[]) => list.reduce((t, s) => t + byStatus[s], 0)
	const rows = n('total_rows')
	const kept = n('candidate_rows')
	const merged = n('duplicate_rows_collapsed')
	// Ownership status alone does not establish a registry property link: an explicit seller
	// can be a former owner even when no sale or property was found.
	const matched = summary.properties_linked_rows ?? null
	return {
		ownerMatch: ownerMatchView(summary.owner_match),
		rows,
		kept,
		properties: summary.distinct_properties ?? null,
		sourceProperties: summary.source_property_counts ?? null,
		salesHistoryRows: summary.rows_with_sales_history ?? null,
		plotOnlyRows: summary.plot_only_rows ?? null,
		merged,
		dropped: Math.max(0, rows - kept - merged),
		matched,
		failed: sum(FAILED_STATUSES),
		validContacts: n('valid_contacts'),
		readyToContact: n('contact_ready'),
		rentalLeads: n('rental_opportunities'),
		matchRate: kept && matched !== null ? matched / kept : null,
		sourceMatchRate: rows && matched !== null ? matched / rows : null,
		droppedByReason: summary.dropped_by_reason ?? {},
		droppedLog: summary.dropped_log ?? false,
		byStatus
	}
}

export interface SheetCheck {
	level: 'error' | 'warning'
	code: 'no_name' | 'no_role' | 'no_property' | 'no_unit' | 'no_price' | 'no_contact'
	text: string
}

type SheetLike = Pick<CrmSheetMapping, 'sheet_family' | 'field_map' | 'warnings'>

/** The backend's own warning when it takes the project name from the file name. */
const INFERRED_PROJECT = 'Property name will be inferred as'

/** What the sheet's mapping means for its rows, errors first. */
export function mappingChecks(sheet: SheetLike): SheetCheck[] {
	const has = (field: string) => Boolean(sheet.field_map?.[field])
	const checks: SheetCheck[] = []
	if (!has('contact_name'))
		checks.push({ level: 'error', code: 'no_name', text: 'No name column: every row is dropped.' })
	if (sheet.sheet_family === 'transaction_party' && !has('party_role'))
		checks.push({
			level: 'warning',
			code: 'no_role',
			text: 'No party-role column: source records are retained for ownership review.'
		})
	// Without date + price the backend has no sale to recover the property from, so it needs a
	// location (building, project, master project or a name inferred from the file) and a unit.
	const saleSignature = has('transaction_date') && has('transaction_price_aed')
	const location =
		has('building_name') ||
		has('project_name') ||
		has('master_project') ||
		(sheet.warnings ?? []).some((w) => w.startsWith(INFERRED_PROJECT))
	if (!location && !saleSignature)
		checks.push({
			level: 'error',
			code: 'no_property',
			text: "No building or project and no date + price: rows can't be tied to a property."
		})
	else if (!has('unit_number') && !saleSignature)
		checks.push({
			level: 'error',
			code: 'no_unit',
			text: "No unit column and no date + price: rows can't be matched to a unit."
		})
	if (has('transaction_date') && !has('transaction_price_aed'))
		checks.push({
			level: 'warning',
			code: 'no_price',
			text: 'No price column: sale-date matching is weaker.'
		})
	if (!has('phone_primary') && !has('phone_alternate') && !has('email_primary'))
		checks.push({ level: 'warning', code: 'no_contact', text: 'No phone or email column.' })
	return checks
}

/** An import worth a second look: it failed, or a sheet has an error-level check. */
export function isFlagged(status: string, sheets: SheetLike[]): boolean {
	return (
		status === 'failed' || sheets.some((s) => mappingChecks(s).some((c) => c.level === 'error'))
	)
}

/** The page start to show once the rows total changed: the last page that still has rows. */
export function clampOffset(offset: number, total: number, limit: number): number {
	if (!total) return 0
	return Math.min(offset, Math.floor((total - 1) / limit) * limit)
}

/** How to fix a file so its rows stop failing, per failed status. */
const FAILURE_FIX: Partial<Record<ClaimStatus, string>> = {
	insufficient_property_data:
		'Add a building (or project) and a unit column, or a sale date and price, then upload again.',
	registry_not_observed:
		'Check the unit number and building spelling; the unit may have no sale on record yet.',
	unmatched:
		'Add or correct the building name so the unit can be told apart from same-numbered units elsewhere.'
}

export interface FailureReason {
	status: ClaimStatus
	label: string
	meaning: string
	fix: string
	count: number
}

/** Why rows failed to match DLD: each failed status with rows, biggest first. */
export function failureReasons(c: ImportCounts): FailureReason[] {
	return FAILED_STATUSES.filter((s) => c.byStatus[s] > 0)
		.map((s) => ({
			status: s,
			label: STATUS_INFO[s].label,
			meaning: STATUS_INFO[s].meaning,
			fix: FAILURE_FIX[s] ?? '',
			count: c.byStatus[s]
		}))
		.sort((a, b) => b.count - a.count)
}

const MISSING = new Set(['', '-', 'n/a', 'na', 'none', 'null', 'unknown'])
const present = (v: string | null | undefined) =>
	!MISSING.has(
		String(v ?? '')
			.trim()
			.toLowerCase()
	)

/**
 * Why a row is "Insufficient property data", from the row itself: which of unit and building /
 * project the file was missing, and whether it had a sale date and price to look the property up
 * by. (The backend gives one generic sentence for all of these.)
 */
export function insufficientReason(row: {
	building: string
	unit: string
	date: string | null
	price: number | null
}): string {
	const unit = present(row.unit)
	const building = present(row.building)
	const missing =
		!unit && !building
			? 'No unit number and no building or project in the file'
			: !unit
				? 'No unit number in the file'
				: !building
					? 'No building or project in the file'
					: 'The unit could not be tied to a property'
	return row.date && row.price
		? `${missing}. Its sale date and price did not match a recorded sale in this location.`
		: `${missing}, and no sale date and price to look the property up in sales records.`
}

export type DropReason = 'no_name' | 'not_buyer_seller' | 'not_a_sale' | 'no_unit'

/** Where in the import a row was dropped: while reading the file, or after checking DLD. */
export type DropStage = 'before_match' | 'after_match'

export const DROP_STAGE_LABEL: Record<DropStage, string> = {
	before_match: 'Before DLD matching',
	after_match: 'After DLD matching'
}

/** Why an import did not keep a row, in the order the import checks them. */
export const DROP_REASON_INFO: Record<
	DropReason,
	{ label: string; meaning: string; stage: DropStage }
> = {
	no_name: {
		label: 'No name',
		meaning: 'The name cell is empty, so there is no owner to keep',
		stage: 'before_match'
	},
	not_buyer_seller: {
		label: 'Not Buyer/Seller',
		meaning: 'A transaction row for another party (bank, mortgagee, developer…)',
		stage: 'before_match'
	},
	not_a_sale: {
		label: 'Not a sale',
		meaning: 'A Buyer/Seller row for a mortgage, gift, grant or other non-sale procedure',
		stage: 'before_match'
	},
	no_unit: {
		label: 'No unit',
		meaning: 'No unit in the file, and none could be recovered from DLD',
		stage: 'after_match'
	}
}

/** The values a dropped-row explanation needs (a row of the dropped-rows log). */
export interface DroppedRowFacts {
	reason: DropReason
	role: string
	procedure: string
	date: string
	price: string
}

export interface DropDetail {
	stage: DropStage
	/** What happened to this row, with the file's own values. */
	what: string
	/** The rule the import applies. */
	rule: string
	/** What would have kept the row. */
	fix: string
}

/**
 * The full reason one row was dropped, in the words of the import's rules
 * (backend import_parsing._candidate_from_row / _is_transfer_candidate and
 * identity._drop_candidates_without_unit).
 */
export function dropDetail(r: DroppedRowFacts): DropDetail {
	const stage = DROP_REASON_INFO[r.reason].stage
	switch (r.reason) {
		case 'no_name':
			return {
				stage,
				what: 'The name cell of this row is empty.',
				rule: 'Every kept row needs an owner name; a row without one has no one to contact.',
				fix: 'Fill in the owner name in the file and upload it again.'
			}
		case 'not_buyer_seller':
			return {
				stage,
				what: r.role
					? `The role is “${r.role}”, which is not Buyer or Seller.`
					: 'The role is empty: this sheet has no Buyer/Seller column mapped, or the cell is blank.',
				rule: 'On a transaction sheet only the Buyer or Seller of a sale is an owner; banks, mortgagees and other parties are not kept.',
				fix: r.role
					? 'Nothing to fix if this party is not an owner.'
					: 'If the sheet is a list of owners, map its role column (or import it as a contact list) and upload again.'
			}
		case 'not_a_sale':
			return {
				stage,
				what: `The procedure is “${r.procedure}”, which is not a sale.`,
				rule: 'A Buyer/Seller row is kept only when its procedure is empty or contains “sale”, “sell” or “delayed sell”. Mortgages, gifts and grants are not sales.',
				fix: 'Nothing to fix: the owner is usually kept from the row of the actual sale.'
			}
		case 'no_unit':
			return {
				stage,
				what: `The file has no unit for this row, and DLD matching could not find one${
					r.date || r.price
						? ` from its date and price (${[r.date, r.price].filter(Boolean).join(', ')})`
						: ''
				}.`,
				rule: 'A row needs a unit to identify a property; it is dropped only after DLD matching has tried to recover the unit.',
				fix: 'Add the unit number in the file and upload it again.'
			}
	}
}

// ---------------------------------------------------------------------------------------------
// Property-first match results: distinct units by tier, row outcomes, reasons, columns read.
// ---------------------------------------------------------------------------------------------

export type MatchBucketKey = 'confirmed' | 'review' | 'property_only' | 'not_matched'

export interface MatchBucket {
	key: MatchBucketKey
	label: string
	tone: Tone
	units: number
	/** Whole percent of the file's distinct units. */
	percent: number
	/** Plain-English meaning, for the ⓘ. */
	meaning: string
}

export interface ReviewReason {
	key: string
	label: string
	/** Rows whose main reason for review this is. */
	count: number
	meaning: string
}

export interface OwnerMatchView {
	version: string
	/** Distinct units in the file. */
	total: number
	/** Confirmed units: the report's headline. */
	headline: { units: number; total: number; percent: number }
	buckets: MatchBucket[]
	/** Rows (not units) that need a look, with one main reason each; largest first. */
	review: { rows: number; reasons: ReviewReason[] }
	/** Distinct sales tied to confirmed rows; null when the import predates the count. */
	sales: { total: number; withUnit: number; withoutUnit: number } | null
	/** Rows that carry no unit identifier at all. */
	rowsWithoutUnit: number
	/** Bank rows on mortgage sales, left out because they are not owners. */
	lenderRows: number
	/** Licensed real-estate brokers named in the file, left out because they are not owners. */
	brokerRows: number
}

/** Why a row sits under review, in the words a person reads. */
export const REVIEW_REASON_INFO: Record<string, { label: string; meaning: string }> = {
	date_differs: {
		label: 'Sale date differs',
		meaning: 'Amount and unit match, but the sale is more than 90 days from the file’s date.'
	},
	unit_differs: {
		label: 'Unit number differs',
		meaning: 'A sale matches the amount and size under another unit number.'
	},
	two_units_named: {
		label: 'Two units named',
		meaning: 'The file names two units for the same sale.'
	},
	share_differs: {
		label: 'Different share sold',
		meaning: 'The sale was for a different share of the unit.'
	},
	size_differs: {
		label: 'Size differs',
		meaning: 'The file’s size is on a different basis from the sale’s.'
	},
	unit_unverified: {
		label: 'Unit not confirmed',
		meaning: 'The sale has no unit number, so it could not be tied to this unit.'
	},
	type_differs: {
		label: 'Property type differs',
		meaning: 'The file and the sale describe a different kind of property.'
	},
	other: { label: 'Other', meaning: 'A detail of the match needs a look.' }
}

const BUCKETS: Record<MatchBucketKey, Pick<MatchBucket, 'label' | 'tone' | 'meaning'>> = {
	confirmed: {
		label: 'Confirmed with a sale',
		tone: 'green',
		meaning: 'The owner is tied to a sale of this unit at this exact price (within AED 2).'
	},
	review: {
		label: 'Needs review',
		tone: 'amber',
		meaning: 'A sale fits the price and size, but one detail disagrees, such as the unit number.'
	},
	property_only: {
		label: 'Property found, no sale',
		tone: 'blue',
		meaning:
			'The unit exists in the Transactions data, but no sale at this price. Often a mortgage row, whose amount is a loan.'
	},
	not_matched: {
		label: 'Not matched',
		tone: 'neutral',
		meaning:
			'The unit could not be identified, the row has no price, or the Transactions data contradicts the sheet (for example the unit’s size).'
	}
}

const percentOf = (n: number, of: number) => (of ? Math.round((n / of) * 100) : 0)

/** The Match result card's numbers; null while an older import waits for its re-match. */
export function ownerMatchView(m: OwnerMatchSummary | null | undefined): OwnerMatchView | null {
	if (!m?.units) return null
	const { total } = m.units
	const bucket = (key: MatchBucketKey): MatchBucket => ({
		key,
		...BUCKETS[key],
		units: m.units[key],
		percent: percentOf(m.units[key], total)
	})
	const buckets = (['confirmed', 'review', 'property_only', 'not_matched'] as const).map(bucket)
	const reasons = Object.entries(m.review_reasons ?? {})
		.filter(([, count]) => count > 0)
		.map(([key, count]) => ({
			key,
			label: (REVIEW_REASON_INFO[key] ?? { label: fieldLabel(key) }).label,
			count,
			meaning: REVIEW_REASON_INFO[key]?.meaning ?? ''
		}))
		.sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
	const sold = m.sales_matched
	return {
		version: m.version,
		total,
		headline: { units: m.units.confirmed, total, percent: buckets[0].percent },
		buckets,
		review: {
			rows: m.rows?.matched_sale_review ?? reasons.reduce((t, r) => t + r.count, 0),
			reasons
		},
		// `registry` counts sales from unit-level records, `transactions` those found only in
		// registry-wide data without a unit number.
		sales: sold
			? {
					total: sold.total ?? (sold.registry ?? 0) + (sold.transactions ?? 0),
					withUnit: sold.registry ?? 0,
					withoutUnit: sold.transactions ?? 0
				}
			: null,
		rowsWithoutUnit: m.rows_without_unit ?? 0,
		lenderRows: m.rows?.lender ?? 0,
		brokerRows: m.rows?.broker ?? 0
	}
}

export type MatchFilterId = 'all' | MatchBucketKey | 'lender' | 'broker'

/**
 * The chips above the rows. Most filter by colour; "Not matched", "Lender" and "Broker" filter by
 * outcome because all are grey (a lender or broker is not an unmatched owner).
 */
export const MATCH_FILTERS: {
	id: MatchFilterId
	label: string
	colours: MatchColour[]
	outcomes: string[]
}[] = [
	{ id: 'all', label: 'All', colours: [], outcomes: [] },
	{ id: 'confirmed', label: 'Confirmed', colours: ['green'], outcomes: [] },
	{ id: 'review', label: 'Needs review', colours: ['amber'], outcomes: [] },
	{ id: 'property_only', label: 'Property only', colours: ['blue'], outcomes: [] },
	{ id: 'not_matched', label: 'Not matched', colours: [], outcomes: ['rejected', 'no_evidence'] },
	{ id: 'lender', label: 'Lender', colours: [], outcomes: ['lender'] },
	{ id: 'broker', label: 'Broker', colours: [], outcomes: ['broker'] }
]

const OUTCOME_LABEL: Record<string, string> = {
	matched_sale: 'Confirmed',
	matched_sale_inferred_unit: 'Confirmed, unit inferred',
	matched_registry_sale: 'Confirmed',
	matched_registry_sale_no_unit: 'Confirmed, no unit',
	matched_sale_via_mortgage: 'Confirmed via mortgage',
	matched_sale_review: 'Needs review',
	property_confirmed_no_sale: 'Property found, no sale',
	rejected: 'Contradicted',
	no_evidence: 'Not matched',
	lender: 'Lender',
	broker: 'Broker'
}

const COLOUR_INFO: Record<MatchColour, { label: string; tone: Tone }> = {
	green: { label: 'Confirmed', tone: 'green' },
	amber: { label: 'Needs review', tone: 'amber' },
	blue: { label: 'Property found, no sale', tone: 'blue' },
	red: { label: 'Contradicted', tone: 'red' },
	grey: { label: 'Not matched', tone: 'neutral' }
}

/** The outcome chip of a row; null when the row has no matcher result yet. */
export function matchOutcomeInfo(
	outcome: string | null | undefined,
	colour: string | null | undefined
): { label: string; tone: Tone } | null {
	const c = COLOUR_INFO[colour as MatchColour]
	if (!outcome && !c) return null
	return {
		label: OUTCOME_LABEL[outcome ?? ''] ?? c?.label ?? 'Not matched',
		tone: c?.tone ?? 'neutral'
	}
}

/** `['101', '102']` or `101, 102` as "101, 102". */
const plainList = (raw: string) =>
	raw
		.replace(/[[\]'"]/g, '')
		.split(',')
		.map((v) => v.trim())
		.filter(Boolean)
		.join(', ')

const sentence = (text: string) => (/[.!?]$/.test(text) ? text : `${text}.`)

/** What follows the first ": " of a matcher note, as a clause. */
const tail = (text: string) => {
	const at = text.indexOf(':')
	return at === -1 ? '' : text.slice(at + 1).trim()
}
/** The bracketed list right after a code, "sheet_names_two_units ['a', 'b']: …". */
const listIn = (text: string) => /\[([^\]]*)\]/.exec(text)?.[1] ?? ''

/** Whole days between two ISO dates; null when either is not a date. */
function daysBetween(a: string, b: string): number | null {
	const x = Date.parse(a.slice(0, 10))
	const y = Date.parse(b.slice(0, 10))
	return Number.isNaN(x) || Number.isNaN(y) ? null : Math.round(Math.abs(x - y) / 86_400_000)
}

type Explainer = [RegExp, (text: string, m: RegExpExecArray) => string]

const EXPLAINERS: Explainer[] = [
	[
		/^date_differs:\s*sheet (\S+),\s*sale (\S+)$/i,
		(_t, m) => {
			const days = daysBetween(m[1], m[2])
			return days === null
				? 'The sale date differs from the file.'
				: `The sale date differs from the file by ${days === 1 ? '1 day' : `${fmt(days)} days`}.`
		}
	],
	[/^date_differs/i, () => 'The sale date differs from the file.'],
	[/^unit_unverified/, () => 'The sale has no unit number, so it could not be tied to this unit.'],
	[
		/^unit differs: Transactions says (.+?), sheet says (.+)$/i,
		(_t, m) =>
			`Transactions has this sale under another unit number: it says ${m[1]}, the sheet says ${plainList(m[2])}.`
	],
	[/^unit differs/i, () => 'Transactions has this sale under another unit number.'],
	[
		/^sheet_names_two_units/,
		(t) => {
			const units = plainList(listIn(t))
			const rest = tail(t)
			return `The sheet names two different units${units ? ` (${units})` : ''}${rest ? `: ${rest}` : ''}.`
		}
	],
	[
		/^sheet_names_two_villas/,
		(t) => `The sheet names two different villas${tail(t) ? `: ${tail(t)}` : ''}.`
	],
	[
		/^eliminated( units)?/,
		(t) => {
			const units = plainList(listIn(t))
			return `Other units with a sale at this price were ruled out${units ? `: ${units}` : ''}.`
		}
	],
	[
		/^elimination_unverified/,
		(t) => `Ruling out the other units could not be checked${tail(t) ? `: ${tail(t)}` : ''}.`
	],
	[
		/^size_basis_differs/,
		() =>
			"The sheet's size fits the sale on a different basis (for example plot area instead of built-up)."
	],
	[/^size_conflict/, () => 'The unit’s size doesn’t fit the sheet.'],
	[/^share_sale/, () => 'The sale was for a share of the unit, not the whole unit.'],
	[
		/^share_qualifier_differs/,
		(t) => `Another share of this unit sold at this price${tail(t) ? `: ${tail(t)}` : ''}.`
	],
	[
		/^buildingno_renumbered/,
		(t) =>
			`The sheet numbers the villas differently from Transactions${tail(t) ? `: ${tail(t)}` : ''}.`
	],
	[
		/^learned_unit_alias/,
		() => 'The unit number was learned from other rows in this file that point to the same unit.'
	],
	[
		/^financing_row/,
		() => 'A mortgage or other financing row: its amount is a loan, not a sale price.'
	],
	[/^no_amount/, () => 'The row has no price to match against a sale.'],
	[/^no_place_no_identifier/, () => 'The row has no building, project or unit number.'],
	[/^no_place/, () => 'The row names no building or project that could be found.'],
	[/^unit_not_in_dxbi/, () => 'This unit is not in the Transactions data.'],
	[
		/^ambiguous_unit/,
		() => 'This unit number exists in several buildings; none sold at this price.'
	],
	[/^(\d+) properties: /, (_t, m) => `${m[1]} properties have this unit number.`],
	[/^no_sale_at_price_and_size/, () => 'No sale in the place fits this price and size.'],
	[
		/^ambiguous_price_size/,
		() =>
			'Several properties in the place have a sale at this price and size, so none can be chosen.'
	],
	[
		/^only property with a sale at this price and size in the place; size read as (\S+)/,
		(_t, m) =>
			`The unit was inferred: it is the only property in the place with a sale at this price and size (size read as ${m[1]}).`
	],
	[
		/^unit (\S+) sold on (\S+)$/,
		() =>
			'A mortgage registered the same day the unit sold: the owner bought it with this mortgage.'
	],
	[
		/^unit (\S+) is (.+) sqft$/,
		(_t, m) => `Unit ${m[1]} is ${m[2].replace(/[[\]'"]/g, '')} sqft in Transactions.`
	],
	[
		/^A bank or finance company on a financing row/,
		() => 'A bank or finance company on a mortgage row: the lender, not an owner.'
	],
	[/^ambiguous_registry_sale/, () => 'More than one sale fits this place and size.'],
	[/^repeat_price/, () => 'This unit sold more than once at this price.'],
	[
		/^type_label_differs \((.+) vs (.+)\)$/,
		(_t, m) =>
			sameTypeFamily(m[1], m[2]) ? '' : `The sheet says ${m[1]}, Transactions says ${m[2]}.`
	],
	[
		/^unit (\S+) exists in DXBI but has no sale within (\d+) AED/,
		(_t, m) =>
			`Unit ${m[1]} is in the Transactions data, but no sale is within AED ${m[2]} of this price.`
	],
	[/^unit (\S+) in (.+)$/, (_t, m) => `Unit ${m[1]} in ${m[2]}.`],
	[
		/^Transactions: (\d+) sale\(s\) fit place and size, (\d+) belong to other units/,
		(_t, m) =>
			`Transactions has ${m[1]} ${m[1] === '1' ? 'sale' : 'sales'} at this price for this place and size` +
			(m[2] === '0'
				? ''
				: `; ${m[2]} other ${m[2] === '1' ? 'sale belongs' : 'sales belong'} to other units`) +
			'.'
	],
	[/^dld_only (.+)$/, (_t, m) => `A land-registry sale with no unit number (${m[1]}).`],
	[/^matched (.+)$/, (_t, m) => `A sale record (${m[1]}).`]
]

// Labels for one kind of property: a difference between two of them says nothing.
const TYPE_FAMILIES = [
	[
		'flat',
		'unit',
		'apartment',
		'apartments',
		'hotel apartment',
		'hotel apartments',
		'hotel rooms',
		'hotel room'
	],
	['villa', 'villas', 'residential', 'building', 'townhouse']
]

function sameTypeFamily(a: string, b: string): boolean {
	const x = a.trim().toLowerCase()
	const y = b.trim().toLowerCase()
	return TYPE_FAMILIES.some((family) => family.includes(x) && family.includes(y))
}

/** Keep provider names out of matcher diagnostics, including older server responses. */
function publicMatchText(text: string): string {
	return text.replace(
		/\b(?:Dubai Land Department|DXB\s*Interact|DXBI|DLD)(?:['’]s)?\b/gi,
		'market data'
	)
}

/** A matcher reason or warning in plain words, without internal provider attribution. */
export function explainMatch(code: string): string {
	const text = code.trim()
	if (!text) return ''
	for (const [pattern, say] of EXPLAINERS) {
		const m = pattern.exec(text)
		if (m) {
			const said = say(text, m)
			return said ? sentence(publicMatchText(said)) : ''
		}
	}
	return publicMatchText(text)
}

/** "1203 · Burj Crown · AED 2,150,000 · 21 Mar 2024": the sale a row was tied to. */
export function matchedSaleLine(sale: MatchedSale | null | undefined): string {
	if (!sale) return ''
	const place = sale.building || sale.project || sale.area
	return [
		sale.unit,
		place,
		sale.amount_aed ? aed(sale.amount_aed) : '',
		sale.date ? fullDate(sale.date.slice(0, 10)) : ''
	]
		.filter(Boolean)
		.join(' · ')
}

const FIELD_LABEL: Record<string, string> = {
	contact_name: 'Owner name',
	phone_primary: 'Phone',
	phone_alternate: 'Second phone',
	email_primary: 'Email',
	area_name: 'Community',
	master_project: 'Master project',
	project_name: 'Project',
	building_name: 'Building',
	unit_number: 'Unit number',
	property_type: 'Property type',
	completion_status: 'Completion status',
	size_sqft: 'Size (sqft)',
	size_sqm: 'Size (sqm)',
	size_unknown: 'Size (unit not stated)',
	transaction_date: 'Sale date',
	transaction_price_aed: 'Sale price (AED)',
	party_role: 'Buyer or seller',
	procedure_type: 'Procedure',
	building_number: 'Building number',
	land_number: 'Land number',
	land_sub_number: 'Land sub-number',
	property_number: 'Property number',
	plot_number: 'Plot number',
	municipality_number: 'Municipality number',
	municipality_sub_number: 'Municipality sub-number'
}

/** A field's name as people say it: "Building", "Sale price (AED)". */
export const fieldLabel = (field: string) => {
	if (FIELD_LABEL[field]) return FIELD_LABEL[field]
	const words = field.replaceAll('_', ' ')
	return words.charAt(0).toUpperCase() + words.slice(1)
}

const NOT_IMPORTED = 'Columns not imported:'

/** The fields a person expects a file to carry, in the order they read them. */
const READ_FIELDS: { label: string; keys: string[]; sale?: boolean }[] = [
	{ label: 'Owner name', keys: ['contact_name'] },
	{ label: 'Phone', keys: ['phone_primary', 'phone_alternate'] },
	{ label: 'Email', keys: ['email_primary'] },
	{ label: 'Community', keys: ['area_name'] },
	{ label: 'Master project', keys: ['master_project'] },
	{ label: 'Project', keys: ['project_name'] },
	{ label: 'Building', keys: ['building_name'] },
	{ label: 'Unit number', keys: ['unit_number'] },
	{ label: 'Property type', keys: ['property_type'] },
	{ label: 'Size', keys: ['size_sqft', 'size_sqm', 'size_unknown'] },
	{ label: 'Sale date', keys: ['transaction_date'], sale: true },
	{ label: 'Sale price', keys: ['transaction_price_aed'], sale: true },
	{ label: 'Buyer or seller', keys: ['party_role'], sale: true },
	{ label: 'Procedure', keys: ['procedure_type'], sale: true }
]

/**
 * Our fields with whether the file has a column for each, from the field keys the mapping found.
 * Sale fields (date, price, buyer or seller, procedure) are listed only when `sale` is set or the
 * file has one of them.
 */
export function fieldChecklist(
	mapped: Iterable<string>,
	sale: boolean
): { field: string; found: boolean }[] {
	const keys = new Set(mapped)
	const known = new Set(READ_FIELDS.flatMap((f) => f.keys))
	const core = READ_FIELDS.map((f) => ({
		field: f.label,
		found: f.keys.some((k) => keys.has(k)),
		sale: f.sale
	}))
		.filter((f) => f.found || sale || !f.sale)
		.map(({ field, found }) => ({ field, found }))
	const extra = [...keys]
		.filter((k) => !known.has(k))
		.map((k) => ({ field: fieldLabel(k), found: true }))
	return [...core, ...extra]
}

const AUTO_NOTE: Record<string, string> = {
	llm: 'Columns were assigned automatically because the headers were not recognised.',
	reused: 'Columns were reused from an earlier import of a file with the same headers.',
	override: 'Columns were set by hand for this file.'
}

/**
 * A reading note without the file's own column names (the importer words some of them with a
 * header); null drops it.
 */
function plainWarning(w: string): string | null {
	if (/^Size has no stated unit/.test(w)) return w
	if (/^Property name will be inferred/.test(w)) return w
	if (/^Dates in .* read month first/.test(w)) return 'Dates were read month first (MM/DD/YYYY).'
	if (/^Dates in .* mix day-first/.test(w))
		return 'Some dates mix day-first and month-first; the unclear ones were left empty.'
	if (/dates? in .* could not be read/.test(w)) return 'Some dates could not be read.'
	return null
}

export interface ColumnsRead {
	name: string
	/** The mapping did not come from the built-in header names (assigned, earlier import or hand). */
	auto: boolean
	sourceNote: string
	/** Our fields, and whether the file has a column for each. */
	fields: { field: string; found: boolean }[]
	/** Columns with data that no field uses. */
	unused: number
	/** Other notes from reading the sheet. */
	warnings: string[]
	checks: SheetCheck[]
}

/** One sheet's "Columns read" panel: our field names only, never the file's own headers. */
export function columnsRead(sheet: ImportSheet): ColumnsRead {
	const unmapped = sheet.warnings.find((w) => w.startsWith(NOT_IMPORTED))
	return {
		name: sheet.name,
		auto: sheet.source in AUTO_NOTE,
		sourceNote: AUTO_NOTE[sheet.source] ?? '',
		fields: fieldChecklist(
			sheet.fields.map((f) => f.field),
			sheet.family !== 'contact_list'
		),
		unused: unmapped
			? unmapped
					.slice(NOT_IMPORTED.length)
					.replace(/\.\s*$/, '')
					.split(',')
					.filter((c) => c.trim()).length
			: 0,
		warnings: sheet.warnings
			.filter((w) => w !== unmapped)
			.map(plainWarning)
			.filter((w): w is string => w !== null),
		checks: sheet.checks
	}
}
