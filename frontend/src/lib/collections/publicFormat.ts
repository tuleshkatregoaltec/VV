export function formatAed(price: number | null | undefined, rentPeriod?: string | null): string {
	if (price == null) return ''
	const amount = `AED ${new Intl.NumberFormat('en-US').format(price)}`
	return rentPeriod === 'yearly' ? `${amount} / year` : amount
}

export function relativeTime(iso: string, now: Date = new Date()): string {
	const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000)
	if (Number.isNaN(seconds) || seconds < 60) return 'just now'
	const units: [number, string][] = [
		[86400, 'day'],
		[3600, 'hour'],
		[60, 'minute']
	]
	for (const [size, label] of units) {
		if (seconds >= size) {
			const n = Math.floor(seconds / size)
			return `${n} ${label}${n === 1 ? '' : 's'} ago`
		}
	}
	return 'just now'
}
