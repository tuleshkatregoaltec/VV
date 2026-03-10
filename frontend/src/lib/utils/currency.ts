import { feasibilityStore } from '$lib/stores/feasibility.svelte';

/** Convert AED to the current display currency. Store always holds AED. */
export function displayValue(valueInAED: number): number {
	if (feasibilityStore.displayCurrency === 'USD') {
		return valueInAED / feasibilityStore.fxRateAEDtoUSD;
	}
	return valueInAED;
}

export function currencySymbol(): string {
	return feasibilityStore.displayCurrency === 'USD' ? 'USD' : 'AED';
}

/** Area unit conversions. */
export const SQM_PER_SQFT = 0.092903;
export function toSqft(sqm: number): number {
	return sqm / SQM_PER_SQFT;
}
export function fromSqft(sqft: number): number {
	return sqft * SQM_PER_SQFT;
}

/** Format as '000 with brackets for negatives, applying display currency. */
export function displayK(valueInAED: number): string {
	const v = displayValue(valueInAED);
	const k = Math.round(Math.abs(v) / 1000);
	const f = k.toLocaleString('en-AE');
	return v < 0 ? `(${f})` : f;
}
