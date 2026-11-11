/**
 * The leads board: column totals, which columns a dragged card may drop on, and the card's lines.
 * Kept out of the page so the rules are tested on their own.
 */
import type { DealType, LeadRow, LeadStage } from './api/types'
import { stagesFor } from './config'

/** AED 12.4M · AED 850K · AED 9,500 */
export function compactAed(n: number): string {
	if (n >= 1e6) return `AED ${+(n / 1e6).toFixed(1)}M`
	if (n >= 1e3) return `AED ${+(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}K`
	return `AED ${Math.round(n)}`
}

/** The lead's money: a buyer's or tenant's budget, a seller's price, a landlord's rent. */
export function leadMoney(l: LeadRow): { amount: number; deal: DealType } | null {
	const f = l.fields ?? {}
	const v = Number(f.budget_aed || f.target_price_aed || f.expected_rent_aed || 0)
	return v > 0 ? { amount: v, deal: l.deal_type } : null
}

export const moneyLabel = (m: { amount: number; deal: DealType }) =>
	m.deal === 'rent' ? `${compactAed(m.amount)}/yr` : compactAed(m.amount)

/**
 * A column's money, sale and rent apart: adding a yearly rent to a sale price means nothing.
 * Empty when no lead in the column states an amount.
 */
export function columnTotal(rows: LeadRow[]): string {
	let sale = 0
	let rent = 0
	for (const l of rows) {
		const m = leadMoney(l)
		if (!m) continue
		if (m.deal === 'rent') rent += m.amount
		else sale += m.amount
	}
	return [
		sale ? moneyLabel({ amount: sale, deal: 'sale' }) : '',
		rent ? moneyLabel({ amount: rent, deal: 'rent' }) : ''
	]
		.filter(Boolean)
		.join(' · ')
}

/**
 * May this card drop on that column? Not on its own stage, not on a stage of the other group,
 * and an owner without a prior deal (DLD Circular 02-2026) only to Lost. A Vitevue lease nobody
 * has opened yet (id 0) is not a lead yet, so it does not move.
 */
export function canDrop(l: LeadRow, to: LeadStage): boolean {
	if (!l.id || l.stage === to) return false
	if (!stagesFor(l.lead_type).some((s) => s.id === to)) return false
	if (l.gated && to !== 'lost') return false
	return true
}

/** Up to two initials: "Ashwin Vyas" → AV, "ALEXANDRU ION TIRIAC" → AT. */
export function initials(name: string): string {
	const parts = name.trim().split(/\s+/).filter(Boolean)
	if (!parts.length) return '?'
	const first = parts[0][0]
	const last = parts.length > 1 ? parts[parts.length - 1][0] : ''
	return (first + last).toUpperCase()
}

const UNSTATED = new Set(['Not stated', 'Unit not stated', ''])

/** "AED 2M · 2BR apartment in Dubai Marina": the money, then what they want (or the unit). */
export function needLine(l: LeadRow): string {
	const m = leadMoney(l)
	const what = l.summary?.line ?? ''
	return [m ? moneyLabel(m) : '', UNSTATED.has(what) ? '' : what].filter(Boolean).join(' · ')
}
