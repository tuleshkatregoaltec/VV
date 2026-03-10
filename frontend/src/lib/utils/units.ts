/**
 * Unit conversion utilities for area and price per unit area.
 *
 * Database stores:
 * - procedure_area: square meters (sqm)
 * - meter_sale_price: price per square meter (AED/sqm)
 * - actual_area (rentals): square meters (sqm)
 *
 * Conversion factor: 1 sqm = 10.764 sqft
 */

export const SQM_TO_SQFT = 10.764;
export const SQFT_TO_SQM = 1 / SQM_TO_SQFT;

export type AreaUnit = 'sqm' | 'sqft';

/**
 * Convert area from square meters to the target unit
 */
export function convertArea(areaSqm: number, targetUnit: AreaUnit): number {
	if (targetUnit === 'sqft') {
		return areaSqm * SQM_TO_SQFT;
	}
	return areaSqm;
}

/**
 * Convert price per unit area from price/sqm to the target unit
 * Note: When converting to sqft, we divide (smaller area = higher price per unit)
 */
export function convertPricePerArea(priceSqm: number, targetUnit: AreaUnit): number {
	if (targetUnit === 'sqft') {
		return priceSqm / SQM_TO_SQFT;
	}
	return priceSqm;
}

/**
 * Get the label suffix for the current unit
 */
export function getAreaUnitLabel(unit: AreaUnit): string {
	return unit === 'sqft' ? 'sq.ft' : 'sq.m';
}

/**
 * Get the full area label with unit
 */
export function getAreaLabel(unit: AreaUnit): string {
	return `Area (${getAreaUnitLabel(unit)})`;
}

/**
 * Get the price per area label with unit
 */
export function getPricePerAreaLabel(unit: AreaUnit): string {
	return `Price/${getAreaUnitLabel(unit)}`;
}

/**
 * Format area value with appropriate precision
 */
export function formatArea(value: number, unit: AreaUnit): string {
	const converted = convertArea(value, unit);
	return converted.toLocaleString(undefined, {
		minimumFractionDigits: 0,
		maximumFractionDigits: 2
	});
}

/**
 * Format price per area with appropriate precision
 */
export function formatPricePerArea(value: number, unit: AreaUnit): string {
	const converted = convertPricePerArea(value, unit);
	return converted.toLocaleString(undefined, {
		minimumFractionDigits: 0,
		maximumFractionDigits: 2
	});
}
