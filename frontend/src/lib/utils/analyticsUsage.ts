import type { AnalyticsUsage } from '$lib/api/analytics'

export type Usage = 'Residential' | 'Commercial'
export type UsageCounts = Partial<Record<string, { sales?: number; leases?: number }>>

export const USAGES: Usage[] = ['Residential', 'Commercial']

const KIND: Record<Usage, string> = {
	Residential: 'residential',
	Commercial: 'commercial (offices, shops)'
}

export function usageTotal(counts: UsageCounts | undefined, usage: Usage): number {
	const count = counts?.[usage]
	return (count?.sales ?? 0) + (count?.leases ?? 0)
}

// "49 sales · 50 leases"; an empty usage reads "No records".
export function usageCountLabel(counts: UsageCounts | undefined, usage: Usage): string {
	const count = counts?.[usage]
	const sales = count?.sales ?? 0
	const leases = count?.leases ?? 0
	if (!sales && !leases) return 'No records'
	const fmt = (n: number) => n.toLocaleString('en-AE')
	return [
		sales ? `${fmt(sales)} ${sales === 1 ? 'sale' : 'sales'}` : '',
		leases ? `${fmt(leases)} ${leases === 1 ? 'lease' : 'leases'}` : ''
	]
		.filter(Boolean)
		.join(' · ')
}

/**
 * One line naming what the figures cover and where the other usage's records are, so a zero is
 * never unexplained: "Showing commercial (offices, shops) records: this project has no
 * residential sales or leases."
 */
export function usageNote(
	resolved: Usage,
	requested: AnalyticsUsage,
	counts: UsageCounts | undefined,
	scope = 'this project'
): string {
	const other: Usage = resolved === 'Residential' ? 'Commercial' : 'Residential'
	const shown = usageTotal(counts, resolved)
	const elsewhere = usageTotal(counts, other)
	if (!shown) return `No ${KIND[resolved]} sales or leases for ${scope}.`
	if (requested === 'auto' && resolved === 'Commercial' && !elsewhere)
		return `Showing ${KIND.Commercial} records: ${scope} has no residential sales or leases.`
	if (!elsewhere) return `Showing ${KIND[resolved]} records; ${scope} has no ${KIND[other]} ones.`
	return `Showing ${KIND[resolved]} records. ${elsewhere.toLocaleString('en-AE')} ${KIND[other]} records are under ${other}.`
}
