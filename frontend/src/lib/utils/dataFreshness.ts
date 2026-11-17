/** How old a dataset is, relative to a clock the caller supplies. */

export const STALE_AFTER_DAYS = 7

const DAY_MS = 86_400_000

export interface Freshness {
	/** Calendar date in UTC, e.g. "27 May 2026". */
	date: string
	days: number
	ageLabel: string
	stale: boolean
}

const dateFormat = new Intl.DateTimeFormat('en-GB', {
	day: 'numeric',
	month: 'short',
	year: 'numeric',
	timeZone: 'UTC'
})

function parse(value: string | null | undefined): Date | null {
	if (!value) return null
	const parsed = new Date(value)
	return Number.isNaN(parsed.valueOf()) ? null : parsed
}

export function formatDataDate(value: string | null | undefined): string | null {
	const parsed = parse(value)
	return parsed ? dateFormat.format(parsed) : null
}

export function describeAge(days: number): string {
	if (days < 1) return 'today'
	if (days < 30) return days === 1 ? '1 day ago' : `${days} days ago`
	if (days < 60) return `${Math.floor(days / 7)} weeks ago`
	if (days < 730) return `${Math.floor(days / 30.44)} months ago`
	return `${Math.floor(days / 365.25)} years ago`
}

export function freshnessOf(
	value: string | null | undefined,
	now: Date = new Date()
): Freshness | null {
	const parsed = parse(value)
	if (!parsed) return null
	const days = Math.max(0, Math.floor((now.getTime() - parsed.getTime()) / DAY_MS))
	return {
		date: dateFormat.format(parsed),
		days,
		ageLabel: describeAge(days),
		stale: days > STALE_AFTER_DAYS
	}
}

export function newestDate(values: Array<string | null | undefined>): string | null {
	let newest: Date | null = null
	for (const value of values) {
		const parsed = parse(value)
		if (parsed && (!newest || parsed > newest)) newest = parsed
	}
	return newest ? newest.toISOString() : null
}

export function newListingsLabel(snapshotAt: string | null | undefined): string {
	const date = formatDataDate(snapshotAt)
	return date ? `Listed in the 30 days to ${date}` : 'Listed in the 30 days before capture'
}
