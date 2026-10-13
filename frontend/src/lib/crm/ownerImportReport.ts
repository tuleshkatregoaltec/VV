/**
 * Owner import report: the counts and mapping checks a manager reads after an upload. Pure
 * functions over what /contact-imports returns (summary + sheet mappings); no fetching.
 * The checks follow the backend's own rules in backend/app/crm/import_parsing.py.
 */
import type { CrmContactImportSummary, CrmSheetMapping } from '$lib/api/generated/hey-api/types.gen'
import type { Tone } from './api/types'

export type ClaimStatus =
	| 'verified_current_owner'
	| 'probable_current_owner'
	| 'unit_linked_unverified'
	| 'former_owner'
	| 'conflicting_claim'
	| 'insufficient_property_data'
	| 'registry_not_observed'
	| 'unmatched'

/** A DLD property was found for the row. */
export const MATCHED_STATUSES: ClaimStatus[] = [
	'verified_current_owner',
	'probable_current_owner',
	'former_owner',
	'conflicting_claim',
	'unit_linked_unverified'
]
/** No DLD property could be found for the row. */
export const FAILED_STATUSES: ClaimStatus[] = [
	'insufficient_property_data',
	'registry_not_observed',
	'unmatched'
]

export const STATUS_INFO: Record<ClaimStatus, { label: string; meaning: string; tone: Tone }> = {
	verified_current_owner: {
		label: 'Verified owner',
		meaning: 'Date and price match the latest DLD sale',
		tone: 'green'
	},
	probable_current_owner: {
		label: 'Probable owner',
		meaning: 'Date fits the latest DLD sale; no price to compare',
		tone: 'green'
	},
	unit_linked_unverified: {
		label: 'Unit found, not verified',
		meaning: 'The unit is known but the file has no date to check',
		tone: 'amber'
	},
	former_owner: {
		label: 'Former owner',
		meaning: 'Sold since the date in the file',
		tone: 'neutral'
	},
	conflicting_claim: {
		label: 'Conflicts with DLD',
		meaning: 'Price or date does not fit the DLD sales',
		tone: 'red'
	},
	insufficient_property_data: {
		label: 'Insufficient property data',
		meaning: 'No building and unit could be worked out',
		tone: 'red'
	},
	registry_not_observed: {
		label: 'Not in DLD registry',
		meaning: 'The unit is not in the DLD sales data',
		tone: 'red'
	},
	unmatched: {
		label: 'Location ambiguous',
		meaning: 'The unit exists in several buildings; none stood out',
		tone: 'amber'
	}
}

/**
 * How the backend decides each status (backend/app/crm/ownership.py) and what to do about it, for
 * the ⓘ on the import report's status tiles. Sales are DLD sales of the matched unit.
 */
export const STATUS_HELP: Record<ClaimStatus, { how: string; todo: string }> = {
	verified_current_owner: {
		how: 'DLD has a sale of this unit within ±2 days of the file’s date, the price is within 2%, and there is no later sale. Confidence 98%.',
		todo: 'Ready to use: the strongest evidence of current ownership.'
	},
	probable_current_owner: {
		how: 'A DLD sale fits the file’s date (±2 days) but the file has no price to compare (86%), or the file’s date is newer than the latest DLD sale (72%).',
		todo: 'Likely the owner; check before relying on it.'
	},
	unit_linked_unverified: {
		how: 'A unit or lease was linked, but there is no sale or date to prove ownership.',
		todo: 'Check ownership another way.'
	},
	former_owner: {
		how: 'The file lists this person as the Seller (100%), or DLD shows a later sale of the unit more than 2 days after the file’s date (99%).',
		todo: 'Not the current owner: a past relationship, not a lead.'
	},
	conflicting_claim: {
		how: 'A DLD sale is within ±2 days but the price differs by more than 2% (45%), or the date does not fit the unit’s sales history (40%).',
		todo: 'Review the row: the file and DLD disagree.'
	},
	insufficient_property_data: {
		how: 'No unit could be worked out: the row has no unit, and no single DLD sale matches its date and price in its location. Confidence 0%.',
		todo: 'Add a unit or plot number DLD knows to the file and upload it again.'
	},
	registry_not_observed: {
		how: 'The row has a unit, but DLD’s sales data has never recorded it (often off-plan, very new, or a mistyped unit). Confidence 10%.',
		todo: 'Check the unit number; DLD may not list it yet.'
	},
	unmatched: {
		how: 'The unit number exists in several DLD buildings and the file’s building / project did not clearly pick one (needs a score of 55 and a 12-point lead). Confidence 20%.',
		todo: 'Write the building name the way DLD does, then upload again.'
	}
}

const SUMMARY_KEY: Record<ClaimStatus, keyof CrmContactImportSummary> = {
	verified_current_owner: 'verified_current_owners',
	probable_current_owner: 'probable_current_owners',
	unit_linked_unverified: 'unit_linked_unverified',
	former_owner: 'former_owners',
	conflicting_claim: 'conflicting_claims',
	insufficient_property_data: 'insufficient_property_data',
	registry_not_observed: 'registry_not_observed',
	unmatched: 'unmatched'
}

export interface ImportCounts {
	rows: number
	kept: number
	merged: number
	dropped: number
	matched: number
	failed: number
	readyToContact: number
	rentalLeads: number
	/** matched ÷ kept; null when nothing was kept. */
	matchRate: number | null
	byStatus: Record<ClaimStatus, number>
}

export function importCounts(summary: CrmContactImportSummary): ImportCounts {
	const n = (key: keyof CrmContactImportSummary) => summary[key] ?? 0
	const byStatus = Object.fromEntries(
		(Object.keys(SUMMARY_KEY) as ClaimStatus[]).map((s) => [s, n(SUMMARY_KEY[s])])
	) as Record<ClaimStatus, number>
	const sum = (list: ClaimStatus[]) => list.reduce((t, s) => t + byStatus[s], 0)
	const rows = n('total_rows')
	const kept = n('candidate_rows')
	const merged = n('duplicate_rows_collapsed')
	const matched = sum(MATCHED_STATUSES)
	return {
		rows,
		kept,
		merged,
		dropped: Math.max(0, rows - kept - merged),
		matched,
		failed: sum(FAILED_STATUSES),
		readyToContact: n('contact_ready'),
		rentalLeads: n('rental_opportunities'),
		matchRate: kept ? matched / kept : null,
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
			level: 'error',
			code: 'no_role',
			text: 'Transaction sheet with no Buyer/Seller column: all its rows are dropped.'
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
		'Check the unit number and building spelling; DLD may not list this unit yet.',
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
