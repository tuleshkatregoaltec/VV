export function formatFeasibilityNumber(value: number | null | undefined, digits = 0): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	return value.toLocaleString('en-AE', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits
	})
}

export function formatFeasibilityInteger(value: number | null | undefined): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return '—'
	return Math.round(value).toLocaleString('en-AE')
}

export function formatFeasibilityPercent(
	value: number | null | undefined,
	digits = 1,
	fallback = '—'
): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return fallback
	return `${formatFeasibilityNumber(value, digits)}%`
}

export function formatMaybeNumber(
	value: number | null | undefined,
	digits = 1,
	suffix = '%',
	fallback = 'N/A'
): string {
	if (value === null || value === undefined || !Number.isFinite(value)) return fallback
	return `${formatFeasibilityNumber(value, digits)}${suffix}`
}

export function dateToQuarter(isoDate: string): string {
	if (!isoDate) return '—'
	const date = new Date(isoDate)
	if (Number.isNaN(date.getTime())) return isoDate
	const quarter = Math.ceil((date.getMonth() + 1) / 3)
	return `Q${quarter} ${date.getFullYear()}`
}

export function monthsBetween(startIso: string, endIso: string): number | null {
	if (!startIso || !endIso) return null
	const start = new Date(startIso)
	const end = new Date(endIso)
	if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return null
	return (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth())
}

const AS_OF_MONTHS = [
	'Jan',
	'Feb',
	'Mar',
	'Apr',
	'May',
	'Jun',
	'Jul',
	'Aug',
	'Sep',
	'Oct',
	'Nov',
	'Dec'
]

/** "DXBI · as of 14 Nov 2026": which source an input comes from and how current it is. */
export function formatDataAsOf(source: { source: 'dxbi' | 'dld'; as_of?: string | null }): string {
	const name = source.source.toUpperCase()
	const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(source.as_of ?? '')
	if (!match) return `${name} · no records for this area`
	return `${name} · as of ${Number(match[3])} ${AS_OF_MONTHS[Number(match[2]) - 1]} ${match[1]}`
}
