/**
 * The price band portal listings are matched in, around a buyer's or tenant's budget.
 * Mirrors LISTING_BUDGET_BELOW / LISTING_BUDGET_ABOVE in backend/app/crm/matching_policy.py;
 * the backend applies it, this only shows it.
 */
const BELOW = 0.3
const ABOVE = 0.2

export function budgetBand(budget: number): { low: number; high: number } | null {
	if (!budget) return null
	return { low: Math.round(budget * (1 - BELOW)), high: Math.round(budget * (1 + ABOVE)) }
}
