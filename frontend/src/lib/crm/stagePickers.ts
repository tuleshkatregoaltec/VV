import type { ListingCard } from './api/types'

/* Pickers in the lead stage form (Viewing / Offer / Won → which unit; Qualified → property type).
   They use SearchPicker, not native selects: the lists are long (hundreds of agency and company
   listings), native menus do not show in a screen share, and a row needs more than a headline. */

export type Pick = { id: string; label: string; meta?: string }

/** Budget headroom: a unit up to 10% over the lead's budget still counts as fitting. */
const BUDGET_HEADROOM = 1.1

function short(n: number): string {
	if (n >= 1_000_000) return `AED ${(n / 1_000_000).toFixed(1)}M`
	return `AED ${Math.round(n / 1_000)}k`
}

/** Listings for the unit picker: units in the lead's area first, then those within budget. */
export function unitPicks(
	units: ListingCard[],
	lead: { area: string; budget: number | null }
): Pick[] {
	const area = lead.area.trim().toLowerCase()
	const rank = (x: ListingCard) =>
		(area && x.area.trim().toLowerCase() === area ? 2 : 0) +
		(lead.budget && x.price_aed && x.price_aed <= lead.budget * BUDGET_HEADROOM ? 1 : 0)
	return units
		.map((x, i) => ({ x, i, r: rank(x) }))
		.sort((a, b) => b.r - a.r || a.i - b.i)
		.map(({ x }) => ({
			id: x.id,
			label: x.unit,
			meta: [
				x.area,
				x.bedrooms ? `${x.bedrooms}BR` : 'Studio',
				x.price_aed ? `${short(x.price_aed)}${x.deal_type === 'rent' ? ' a year' : ''}` : null,
				x.scope === 'mine' ? 'Your listing' : 'Company'
			]
				.filter(Boolean)
				.join(' · ')
		}))
}

const HOME = [
	'Apartment',
	'Villa',
	'Townhouse',
	'Penthouse',
	'Duplex',
	'Bungalow',
	'Compound',
	'Hotel & Hotel Apartment'
]
const COMMERCIAL = [
	'Whole Building',
	'Full Floor',
	'Half Floor',
	'Bulk Sale Unit',
	'Bulk Rent Unit',
	'Office Space',
	'Business Centre',
	'Co-working space',
	'Retail',
	'Shop',
	'Show Room'
]
const INDUSTRIAL = ['Warehouse', 'Factory', 'Labor Camp', 'Staff Accommodation', 'Land', 'Farm']
const GROUPS: [string, string[]][] = [
	['Home', HOME],
	['Commercial', COMMERCIAL],
	['Industrial & land', INDUSTRIAL]
]

function groupOf(option: string): { name: string; order: number } | null {
	const i = GROUPS.findIndex(([, list]) => list.includes(option))
	return i < 0 ? null : { name: GROUPS[i][0], order: i }
}

/** A field's options for the picker; property types are labelled Home / Commercial / Industrial & land, homes first. */
export function optionPicks(_key: string, options: string[]): Pick[] {
	const grouped = options.some((o) => groupOf(o))
	if (!grouped) return options.map((o) => ({ id: o, label: o }))
	return options
		.map((o, i) => ({ o, i, g: groupOf(o) }))
		.sort((a, b) => (a.g?.order ?? 9) - (b.g?.order ?? 9) || a.i - b.i)
		.map(({ o, g }) => (g ? { id: o, label: o, meta: g.name } : { id: o, label: o }))
}
