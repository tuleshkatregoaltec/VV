import type { ListingCardResponse } from '$lib/api/listings'

/* Market › Listings: how a listing compares with its value (Kian, 11 Nov 2026). Sale listings are
   valued from DLD sales of the same bedroom count in the same building; rent and commercial keep
   the asking-price comparison. The wording says where each number comes from. */

type Card = Pick<
	ListingCardResponse,
	| 'listing_mode'
	| 'market_position'
	| 'market_delta_pct'
	| 'comparable_count'
	| 'valuation_method'
	| 'valuation_confidence'
	| 'value_gap_pct'
	| 'is_off_plan'
>

function pct(value: number | null | undefined): string {
	return `${Math.abs((value ?? 0) * 100).toFixed(1)}%`
}

function offPlanSale(card: Card): boolean {
	return card.listing_mode === 'sale' && card.is_off_plan
}

export function valueLabel(card: Card): string {
	if (offPlanSale(card)) return 'Off-plan · not valued'
	if (card.valuation_method === 'dld_sales') {
		if (card.market_position === 'below_market') return `${pct(card.value_gap_pct)} below value`
		// Asking prices usually sit 5–10% above sale prices: not necessarily overpriced.
		if (card.market_position === 'above_market')
			return `Asking ${pct(card.value_gap_pct)} above sales`
		if (card.market_position === 'near_market') return 'At value'
		return 'Not enough sales'
	}
	if (card.market_position === 'insufficient_data' || card.market_delta_pct == null)
		return 'No benchmark'
	if (card.market_position === 'below_market') return `${pct(card.market_delta_pct)} below`
	if (card.market_position === 'above_market') return `${pct(card.market_delta_pct)} above`
	return `Within market · ${pct(card.market_delta_pct)}`
}

export function valueTone(card: Pick<Card, 'market_position' | 'valuation_method'>): string {
	if (card.market_position === 'below_market')
		return 'border-success-border bg-success-bg text-success'
	if (card.market_position === 'near_market') return 'border-info-border bg-info-bg text-info'
	if (card.market_position === 'above_market')
		return card.valuation_method === 'dld_sales'
			? 'border-warning-border bg-warning-bg text-warning'
			: 'border-error-border bg-error-bg text-error'
	return 'border-border bg-panel text-fg-4'
}

export function basisText(card: Card): string {
	if (offPlanSale(card)) return 'No ready sales to compare with'
	if (card.valuation_method === 'dld_sales') {
		if (card.market_position === 'insufficient_data')
			return 'Too few same-bedroom sales in this building'
		const confidence = card.valuation_confidence ? ` · ${card.valuation_confidence} confidence` : ''
		return `${card.comparable_count.toLocaleString()} recorded sales${confidence}`
	}
	return card.comparable_count
		? `${card.comparable_count.toLocaleString()} peer listings`
		: 'Not enough peer listings'
}

export function dataAgeText(value: string | null | undefined): string | null {
	if (!value) return null
	const parsed = new Date(value)
	if (Number.isNaN(parsed.valueOf())) return null
	const date = new Intl.DateTimeFormat('en-GB', {
		day: 'numeric',
		month: 'short',
		year: 'numeric',
		timeZone: 'UTC'
	}).format(parsed)
	return `Listings collected ${date}`
}
