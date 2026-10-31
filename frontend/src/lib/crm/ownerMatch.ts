/**
 * The "Matching" lines of an owner's unit: each thing the owner file says, next to DLD's latest
 * sale of the unit. These are field comparisons, not a second ownership resolver:
 * the backend assessment considers the complete history, competing parties and missing evidence.
 */
import type { OwnerUnitCheck } from './api/types'
import { ownerPropertyKind } from './config'
import { aed, fullDate } from './format'

export type MatchResult = 'match' | 'differs' | 'info' | 'none'

export interface MatchLine {
	label: string
	file: string
	dld: string
	result: MatchResult
	note: string
}

const DAY = 86_400_000
const DATE_WINDOW_DAYS = 7
const PRICE_TOLERANCE = 0.02

const unitKey = (v: string) => v.toUpperCase().replace(/\s+/g, '')
const day = (v: string | null) => (v ? Date.parse(v.slice(0, 10)) : Number.NaN)

export function matchLines(c: OwnerUnitCheck): MatchLine[] {
	const lines: MatchLine[] = []

	// Unit
	const fileUnit = c.imported.unit
	const dldUnit = c.dld.unit
	lines.push({
		label: 'Unit',
		file: fileUnit || '—',
		dld: dldUnit || '—',
		...(!fileUnit || !dldUnit
			? {
					result: 'none' as const,
					note: dldUnit ? 'No unit in the file' : 'No recorded sale found for this unit'
				}
			: unitKey(fileUnit) === unitKey(dldUnit)
				? { result: 'match' as const, note: 'Same unit' }
				: { result: 'differs' as const, note: 'Different unit' })
	})

	// A nearby date is supporting evidence; it cannot establish the same sale on its own.
	const fileDay = day(c.imported.date)
	const dldDay = day(c.dld.date)
	const days = Math.round((dldDay - fileDay) / DAY)
	const nearbyDate = Number.isFinite(days) && Math.abs(days) <= DATE_WINDOW_DAYS
	lines.push({
		label: 'Sale date',
		file: c.imported.date ? fullDate(c.imported.date) : '—',
		dld: c.dld.date ? fullDate(c.dld.date) : '—',
		...(!Number.isFinite(days)
			? {
					result: 'none' as const,
					note: c.imported.date ? 'No recorded sale to compare' : 'No date in the file'
				}
			: nearbyDate
				? {
						result: 'match' as const,
						note:
							days === 0
								? 'Same date'
								: `Dates within ${DATE_WINDOW_DAYS} days; see ownership assessment`
					}
				: days > 0
					? {
							result: 'differs' as const,
							note: `Latest recorded sale is ${days.toLocaleString('en-US')} days after the file's date; see ownership assessment`
						}
					: {
							result: 'info' as const,
							note: `The file's date is ${Math.abs(days).toLocaleString('en-US')} days after the latest recorded sale`
						})
	})

	// Equal amounts can support a provisional match despite a source-date discrepancy.
	const fileAed = c.imported.aed
	const dldAed = c.dld.aed
	const gap = fileAed && dldAed ? Math.abs(fileAed - dldAed) / dldAed : null
	lines.push({
		label: 'Price',
		file: fileAed ? aed(fileAed) : '—',
		dld: dldAed ? aed(dldAed) : '—',
		...(gap === null
			? {
					result: 'none' as const,
					note: fileAed ? 'No recorded price to compare' : 'No price in the file'
				}
			: gap <= PRICE_TOLERANCE
				? { result: 'match' as const, note: `Within ${PRICE_TOLERANCE * 100}%` }
				: { result: 'differs' as const, note: `Differs by ${(gap * 100).toFixed(1)}%` })
	})

	// A generic Unit is compatible with Apartment; explicit physical kinds still matter.
	const fileType = c.imported.type
	const dldType = c.dld.type
	const fileKind = ownerPropertyKind(fileType)
	const registryKind = ownerPropertyKind(dldType)
	const genericApartment =
		(/^units?$/i.test(fileType.trim()) && registryKind === 'apartment') ||
		(/^units?$/i.test(dldType.trim()) && fileKind === 'apartment')
	lines.push({
		label: 'Property type',
		file: fileType || '—',
		dld: dldType || '—',
		...(!fileType || !dldType
			? { result: 'none' as const, note: 'Property type unavailable' }
			: genericApartment
				? { result: 'match' as const, note: 'Compatible: Unit / Apartment' }
				: fileKind !== 'unspecified' && fileKind === registryKind
					? { result: 'match' as const, note: 'Same property kind' }
					: { result: 'info' as const, note: 'Different descriptions; see ownership assessment' })
	})

	// Keep the source role visible without independently deciding current/former ownership.
	const role = c.imported.role
	lines.push({
		label: 'Role',
		file: role || '—',
		dld: '—',
		...(!role
			? { result: 'none' as const, note: 'No role in the file' }
			: /seller/i.test(role)
				? { result: 'info' as const, note: 'Source says Seller; role retained for review' }
				: { result: 'info' as const, note: 'Source says Buyer; see ownership assessment' })
	})

	return lines
}
