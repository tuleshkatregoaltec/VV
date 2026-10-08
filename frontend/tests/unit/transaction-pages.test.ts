import { describe, expect, it } from 'vitest'

import {
	formatAed,
	PROPERTY_USAGE,
	RENTAL_COLUMNS,
	SALES_COLUMNS
} from '$lib/constants/transactions'
import {
	buildRentalsApiFilters,
	buildRentalsFilterParams,
	buildSalesApiFilters,
	buildSalesFilterParams,
	DEFAULT_RENTALS_LOCAL_FILTERS,
	DEFAULT_SALES_LOCAL_FILTERS,
	toRentalRow,
	toSaleRow,
	withSelectedIds
} from '$lib/utils/transactionPages'

describe('DXBI transaction page filters', () => {
	it('sends every selected sales filter, with half-open bands and the requested page', () => {
		const filters = buildSalesApiFilters({
			propertyUsage: PROPERTY_USAGE.RESIDENTIAL,
			timeframe: 'Last Month',
			currentPage: 2,
			localFilters: {
				selectedLocation: 'Jumeirah Village Circle',
				selectedBuilding: 'Binghatti Heights',
				selectedPropertyType: 'Apartment',
				selectedBedrooms: '2 Beds',
				selectedStatus: 'Ready',
				sizeRange: '1,000-2,000',
				priceRange: '1M-2M',
				pricePerSqFtRange: '1,000-2,000'
			}
		})

		expect(filters).toEqual({
			property_usage: 'Residential',
			timeframe_days: 30,
			limit: 30,
			offset: 30,
			location: 'Jumeirah Village Circle',
			building: 'Binghatti Heights',
			property_type: 'Apartment',
			bedrooms: '2 Beds',
			status: 'Ready',
			size_min: 1_000,
			size_max: 2_000,
			price_min: 1_000_000,
			price_max: 2_000_000,
			price_per_sqft_min: 1_000,
			price_per_sqft_max: 2_000
		})
		expect(withSelectedIds(filters, 'transaction_ids', new Set(['tx-1', 'tx-2']))).toMatchObject({
			transaction_ids: 'tx-1,tx-2'
		})
	})

	it('sends no usage for All, so plots and untyped DXBI records are included', () => {
		const params = buildSalesFilterParams({
			propertyUsage: PROPERTY_USAGE.ALL,
			timeframe: 'Last Year',
			localFilters: { ...DEFAULT_SALES_LOCAL_FILTERS, selectedPropertyType: 'Plot' }
		})

		expect(params).toEqual({ timeframe_days: 365, property_type: 'Plot' })
	})

	it('opens the top bands upward and the bottom bands downward only', () => {
		const top = buildSalesFilterParams({
			propertyUsage: PROPERTY_USAGE.COMMERCIAL,
			timeframe: 'Last Week',
			localFilters: {
				...DEFAULT_SALES_LOCAL_FILTERS,
				sizeRange: '5,000+',
				priceRange: '5M+',
				pricePerSqFtRange: '3,000+'
			}
		})
		expect(top).toEqual({
			property_usage: 'Commercial',
			timeframe_days: 7,
			size_min: 5_000,
			price_min: 5_000_000,
			price_per_sqft_min: 3_000
		})

		const bottom = buildSalesFilterParams({
			propertyUsage: PROPERTY_USAGE.RESIDENTIAL,
			timeframe: 'Last Week',
			localFilters: { ...DEFAULT_SALES_LOCAL_FILTERS, sizeRange: '<500', priceRange: '<500k' }
		})
		expect(bottom).toEqual({
			property_usage: 'Residential',
			timeframe_days: 7,
			size_max: 500,
			price_max: 500_000
		})
	})

	it('sends every selected rentals filter and the selected contracts for export', () => {
		const filters = buildRentalsApiFilters({
			propertyUsage: PROPERTY_USAGE.RESIDENTIAL,
			timeframe: 'Last 6 Months',
			currentPage: 3,
			localFilters: {
				selectedLocation: 'Dubai Marina',
				selectedBuilding: 'Marina Gate 1',
				selectedPropertyType: 'Apartment',
				selectedBedrooms: '1 Bed',
				selectedContractType: 'Renewed',
				sizeRange: '500-1,000',
				rentRange: '50k-100k'
			}
		})

		expect(filters).toEqual({
			property_usage: 'Residential',
			timeframe_days: 180,
			limit: 30,
			offset: 60,
			location: 'Dubai Marina',
			building: 'Marina Gate 1',
			property_type: 'Apartment',
			bedrooms: '1 Bed',
			contract_type: 'Renewed',
			size_min: 500,
			size_max: 1_000,
			rent_min: 50_000,
			rent_max: 100_000
		})
		expect(withSelectedIds(filters, 'contract_ids', new Set(['c-1']))).toMatchObject({
			contract_ids: 'c-1'
		})
		expect(
			buildRentalsFilterParams({
				propertyUsage: PROPERTY_USAGE.RESIDENTIAL,
				timeframe: 'Last 6 Months',
				localFilters: { ...DEFAULT_RENTALS_LOCAL_FILTERS, rentRange: '200k+' }
			})
		).toEqual({ property_usage: 'Residential', timeframe_days: 180, rent_min: 200_000 })
	})
})

describe('DXBI transaction rows', () => {
	it('shows the DXBI unit number and keeps missing values visibly missing', () => {
		const row = toSaleRow({
			transaction_id: 'sale-1',
			transaction_date: '2026-09-15',
			unit_number: '1904',
			building_name: '29 Boulevard Tower 2',
			project_name: null,
			location_name: 'Downtown Dubai',
			property_type: 'Apartment',
			bedrooms: '1 Bed',
			status: 'Ready',
			size_sqft: 799,
			price_aed: 1_750_000,
			price_per_sqft_aed: 2_190
		})

		expect(row).toEqual({
			transaction_id: 'sale-1',
			date: '2026-09-15',
			unit: '1904',
			building: '29 Boulevard Tower 2',
			location: 'Downtown Dubai',
			project: '-',
			propertyType: 'Apartment',
			bedrooms: '1 Bed',
			size: 799,
			price: 1_750_000,
			pricePerSqFt: 2_190,
			status: 'Ready'
		})
		expect(SALES_COLUMNS.map((column) => column.id)).toContain('unit')
	})

	it('maps a lease with its unit, annual rent and whole-contract amount', () => {
		const row = toRentalRow({
			contract_id: 'lease-1',
			lease_start: '2026-09-01',
			lease_end: '2028-08-31',
			unit_number: 'G29',
			building_name: null,
			project_name: null,
			location_name: 'Al Mamzer',
			property_type: 'Commercial',
			bedrooms: null,
			size_sqft: 4_174,
			annual_rent_aed: 220_000,
			contract_amount_aed: 440_000,
			term_months: 24,
			contract_type: 'Renewed'
		})

		expect(row).toMatchObject({
			unit: 'G29',
			building: '-',
			bedrooms: '-',
			annualRent: 220_000,
			contractAmount: 440_000,
			termMonths: 24,
			contractType: 'Renewed'
		})
		expect(RENTAL_COLUMNS.map((column) => column.id)).toContain('unit')
	})

	it('formats amounts identically in every browser locale and shows sizes in sq ft', () => {
		expect(formatAed(1_179_900)).toBe('1,179,900')
		expect(formatAed(null)).toBe('-')
		const size = SALES_COLUMNS.find((column) => column.id === 'size')
		expect(size?.label).toBe('Size (sq ft)')
		expect(size?.format?.(822.6)).toBe('823')
		expect(SALES_COLUMNS.find((column) => column.id === 'pricePerSqFt')?.label).toBe(
			'Price/sq ft (AED)'
		)
	})
})
