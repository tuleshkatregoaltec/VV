// Every area the product shows is in square feet and every price or rent per area in AED per
// square foot. Values the API returns per square foot are shown as they are; the feasibility
// workbook keeps its model in square metres and converts on display and on input.
export const SQM_TO_SQFT = 10.7639
export const SQFT_TO_SQM = 1 / SQM_TO_SQFT

export const AREA_UNIT = 'sq ft'
export const PRICE_PER_AREA_UNIT = 'AED/sq ft'

/** An area in m², in sq ft. */
export function toSqft(sqm: number): number {
	return sqm * SQM_TO_SQFT
}

/** An area typed in sq ft, in m² (the feasibility model's unit). */
export function fromSqft(sqft: number): number {
	return sqft * SQFT_TO_SQM
}

/** An amount per m², per sq ft. */
export function perSqft(valuePerSqm: number): number {
	return valuePerSqm / SQM_TO_SQFT
}

/** An amount typed per sq ft, per m² (the feasibility model's unit). */
export function perSqm(valuePerSqft: number): number {
	return valuePerSqft * SQM_TO_SQFT
}

const wholeNumber = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** Whole square feet, e.g. "1,250"; missing values are "-". */
export function formatSqft(value: number | null | undefined): string {
	return value == null || !Number.isFinite(value) ? '-' : wholeNumber.format(value)
}

/** Whole AED per square foot, e.g. "1,858"; missing values are "-". */
export function formatAedPerSqft(value: number | null | undefined): string {
	return value == null || !Number.isFinite(value) ? '-' : wholeNumber.format(value)
}
