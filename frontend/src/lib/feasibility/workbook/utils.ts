export function formatCurrency(value: number | null | undefined) {
	if (value === null || value === undefined || Number.isNaN(value)) return '—'
	return new Intl.NumberFormat('en-AE', {
		maximumFractionDigits: 0
	}).format(value)
}

export function formatNumber(value: number | null | undefined, digits = 0) {
	if (value === null || value === undefined || Number.isNaN(value)) return '—'
	return new Intl.NumberFormat('en-AE', {
		maximumFractionDigits: digits,
		minimumFractionDigits: digits
	}).format(value)
}

export function titleCase(value: string) {
	return value.replaceAll('_', ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}
