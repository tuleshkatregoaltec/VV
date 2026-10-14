import type {
	RentalContractResponseOutput,
	RentalFacetFilters,
	RentalTransactionFilters,
	SalesFacetFilters,
	SalesTransactionFilters,
	TransactionResponseOutput
} from '$lib/api/transactions'
import {
	DEFAULT_ITEMS_PER_PAGE,
	PROPERTY_USAGE,
	TIMEFRAME_MAPPING
} from '$lib/constants/transactions'

// Bands are half-open: '500-1,000' is 500 up to (not including) 1,000 and '5,000+' is 5,000 and
// above, so a value on a boundary belongs to exactly one band. Sizes are in sq ft.
type Band = { min?: number; max?: number }

const SIZE_BANDS: Record<string, Band> = {
	'<500': { max: 500 },
	'500-1,000': { min: 500, max: 1_000 },
	'1,000-2,000': { min: 1_000, max: 2_000 },
	'2,000-5,000': { min: 2_000, max: 5_000 },
	'5,000+': { min: 5_000 }
}

const SALES_PRICE_BANDS: Record<string, Band> = {
	'<500k': { max: 500_000 },
	'500k-1M': { min: 500_000, max: 1_000_000 },
	'1M-2M': { min: 1_000_000, max: 2_000_000 },
	'2M-5M': { min: 2_000_000, max: 5_000_000 },
	'5M+': { min: 5_000_000 }
}

const SALES_PRICE_SQFT_BANDS: Record<string, Band> = {
	'<1,000': { max: 1_000 },
	'1,000-2,000': { min: 1_000, max: 2_000 },
	'2,000-3,000': { min: 2_000, max: 3_000 },
	'3,000+': { min: 3_000 }
}

const RENT_BANDS: Record<string, Band> = {
	'<50k': { max: 50_000 },
	'50k-100k': { min: 50_000, max: 100_000 },
	'100k-200k': { min: 100_000, max: 200_000 },
	'200k+': { min: 200_000 }
}

export const SIZE_OPTIONS = ['All', ...Object.keys(SIZE_BANDS)]
export const SALES_PRICE_OPTIONS = ['All', ...Object.keys(SALES_PRICE_BANDS)]
export const SALES_PRICE_SQFT_OPTIONS = ['All', ...Object.keys(SALES_PRICE_SQFT_BANDS)]
export const RENT_OPTIONS = ['All', ...Object.keys(RENT_BANDS)]

export interface SalesLocalFilters {
	locationSearch: string
	selectedLocation: string
	selectedBuilding: string
	selectedProject: string
	selectedPropertyType: string
	selectedBedrooms: string
	selectedStatus: string
	sizeRange: string
	priceRange: string
	pricePerSqFtRange: string
}

export interface RentalsLocalFilters {
	locationSearch: string
	selectedLocation: string
	selectedBuilding: string
	selectedProject: string
	selectedPropertyType: string
	selectedBedrooms: string
	selectedContractType: string
	sizeRange: string
	rentRange: string
}

export const DEFAULT_SALES_LOCAL_FILTERS: SalesLocalFilters = {
	locationSearch: '',
	selectedLocation: 'All',
	selectedBuilding: 'All',
	selectedProject: 'All',
	selectedPropertyType: 'All',
	selectedBedrooms: 'All',
	selectedStatus: 'All',
	sizeRange: 'All',
	priceRange: 'All',
	pricePerSqFtRange: 'All'
}

export const DEFAULT_RENTALS_LOCAL_FILTERS: RentalsLocalFilters = {
	locationSearch: '',
	selectedLocation: 'All',
	selectedBuilding: 'All',
	selectedProject: 'All',
	selectedPropertyType: 'All',
	selectedBedrooms: 'All',
	selectedContractType: 'All',
	sizeRange: 'All',
	rentRange: 'All'
}

interface FilterContext {
	propertyUsage: string
	timeframe: string
}

interface PageContext extends FilterContext {
	currentPage: number
}

function isSelected(value: string | null | undefined): value is string {
	return Boolean(value && value !== 'All')
}

function applyBand(
	filters: object,
	selected: string,
	bands: Record<string, Band>,
	minKey: string,
	maxKey: string
) {
	if (!isSelected(selected)) return
	const band = bands[selected]
	if (!band) return
	const mutableFilters = filters as Record<string, number | string | undefined>
	if (band.min !== undefined) mutableFilters[minKey] = band.min
	if (band.max !== undefined) mutableFilters[maxKey] = band.max
}

function baseFilters(context: FilterContext): { property_usage?: string; timeframe_days: number } {
	return {
		// "All" sends no usage: every DXBI record, plots and untyped records included.
		...(context.propertyUsage === PROPERTY_USAGE.ALL
			? {}
			: { property_usage: context.propertyUsage }),
		timeframe_days: TIMEFRAME_MAPPING[context.timeframe]
	}
}

function pagination(currentPage: number) {
	return { limit: DEFAULT_ITEMS_PER_PAGE, offset: (currentPage - 1) * DEFAULT_ITEMS_PER_PAGE }
}

export function buildSalesFilterParams(
	context: FilterContext & { localFilters: SalesLocalFilters }
): SalesFacetFilters {
	const local = context.localFilters
	const filters: SalesFacetFilters = baseFilters(context)
	if (local.locationSearch.trim()) filters.location_search = local.locationSearch.trim()
	if (isSelected(local.selectedLocation)) filters.location = local.selectedLocation
	if (isSelected(local.selectedBuilding)) filters.building = local.selectedBuilding
	if (isSelected(local.selectedProject)) filters.project = local.selectedProject
	if (isSelected(local.selectedPropertyType)) filters.property_type = local.selectedPropertyType
	if (isSelected(local.selectedBedrooms)) filters.bedrooms = local.selectedBedrooms
	if (isSelected(local.selectedStatus)) filters.status = local.selectedStatus
	applyBand(filters, local.sizeRange, SIZE_BANDS, 'size_min', 'size_max')
	applyBand(filters, local.priceRange, SALES_PRICE_BANDS, 'price_min', 'price_max')
	applyBand(
		filters,
		local.pricePerSqFtRange,
		SALES_PRICE_SQFT_BANDS,
		'price_per_sqft_min',
		'price_per_sqft_max'
	)
	return filters
}

export function buildSalesApiFilters(
	context: PageContext & { localFilters: SalesLocalFilters }
): SalesTransactionFilters {
	return { ...buildSalesFilterParams(context), ...pagination(context.currentPage) }
}

export function buildRentalsFilterParams(
	context: FilterContext & { localFilters: RentalsLocalFilters }
): RentalFacetFilters {
	const local = context.localFilters
	const filters: RentalFacetFilters = baseFilters(context)
	if (local.locationSearch.trim()) filters.location_search = local.locationSearch.trim()
	if (isSelected(local.selectedLocation)) filters.location = local.selectedLocation
	if (isSelected(local.selectedBuilding)) filters.building = local.selectedBuilding
	if (isSelected(local.selectedProject)) filters.project = local.selectedProject
	if (isSelected(local.selectedPropertyType)) filters.property_type = local.selectedPropertyType
	if (isSelected(local.selectedBedrooms)) filters.bedrooms = local.selectedBedrooms
	if (isSelected(local.selectedContractType)) filters.contract_type = local.selectedContractType
	applyBand(filters, local.sizeRange, SIZE_BANDS, 'size_min', 'size_max')
	applyBand(filters, local.rentRange, RENT_BANDS, 'rent_min', 'rent_max')
	return filters
}

export function buildRentalsApiFilters(
	context: PageContext & { localFilters: RentalsLocalFilters }
): RentalTransactionFilters {
	return { ...buildRentalsFilterParams(context), ...pagination(context.currentPage) }
}

export function withSelectedIds<T extends SalesTransactionFilters | RentalTransactionFilters>(
	filters: T,
	key: 'transaction_ids' | 'contract_ids',
	selectedIds: Set<string>
): T {
	if (selectedIds.size === 0) return filters

	return {
		...filters,
		[key]: Array.from(selectedIds).join(',')
	} as T
}

export function formatLocation(...parts: (string | null | undefined)[]): string {
	const seen = new Set<string>()
	return (
		parts
			.filter((part): part is string => {
				const key = part?.trim().normalize('NFKC').toLowerCase()
				if (!key || key === '-' || seen.has(key)) return false
				seen.add(key)
				return true
			})
			.map((part) => part.trim())
			.join(' · ') || 'Location unavailable'
	)
}

// Table rows. Missing DXBI text values show as '-', missing numbers as null (formatted '-').
export interface SaleRow {
	transaction_id: string
	date: string
	unit: string
	building: string
	// Unit, building, project, master project and area in one line, and its Google Maps link.
	location: string
	mapUrl: string | null
	community: string
	project: string
	masterProject: string
	dldArea: string
	propertyType: string
	bedrooms: string
	size: number | null
	price: number | null
	pricePerSqFt: number | null
	status: string
}

export interface RentalRow {
	contract_id: string
	startDate: string
	endDate: string
	unit: string
	building: string
	// Unit, building, project, master project and area in one line, and its Google Maps link.
	location: string
	mapUrl: string | null
	community: string
	project: string
	masterProject: string
	dldArea: string
	propertyType: string
	bedrooms: string
	size: number | null
	annualRent: number | null
	contractAmount: number | null
	termMonths: number | null
	contractType: string
}

// Bedrooms describe homes: an office or shop has none to show, a home without one is unrecorded.
const HOME_TYPES = new Set([
	'Apartment',
	'Villa',
	'Townhouse',
	'Hotel Apartment',
	'Penthouse',
	'Duplex'
])

function bedroomsMissing(propertyType: string | null | undefined): string {
	return propertyType && !HOME_TYPES.has(propertyType) ? 'N/A' : '-'
}

// DLD writes many names in capitals ("DAMAC HILLS"); show them as words.
function displayName(value: string | null | undefined): string {
	if (!value) return '-'
	if (value !== value.toUpperCase() || !/[A-Z]{3}/.test(value)) return value
	return value
		.toLowerCase()
		.replace(/(^|[\s(/-])([a-z])/g, (_, lead, letter) => lead + letter.toUpperCase())
}

export function toSaleRow(sale: TransactionResponseOutput): SaleRow {
	return {
		transaction_id: sale.transaction_id,
		date: sale.transaction_date ?? '-',
		unit: sale.unit_number ?? '-',
		building: sale.building_name ?? '-',
		// The profile's line (unit, building, project, master, area); without a profile yet,
		// DXBI's own building, project and community.
		location:
			sale.location ||
			formatLocation(sale.building_name, sale.project_name, sale.location_name),
		mapUrl: sale.map_url || null,
		community: sale.location_name ?? '-',
		project: sale.project_name ?? '-',
		masterProject: displayName(sale.master_project),
		dldArea: displayName(sale.dld_area),
		propertyType: sale.property_type ?? '-',
		bedrooms: sale.bedrooms ?? bedroomsMissing(sale.property_type),
		size: sale.size_sqft ?? null,
		price: sale.price_aed ?? null,
		pricePerSqFt: sale.price_per_sqft_aed ?? null,
		status: sale.status ?? '-'
	}
}

export function toRentalRow(lease: RentalContractResponseOutput): RentalRow {
	return {
		contract_id: lease.contract_id,
		startDate: lease.lease_start ?? '-',
		endDate: lease.lease_end ?? '-',
		unit: lease.unit_number ?? '-',
		building: lease.building_name ?? '-',
		// The profile's line (unit, building, project, master, area); without a profile yet,
		// DXBI's own building, project and community.
		location:
			lease.location ||
			formatLocation(lease.building_name, lease.project_name, lease.location_name),
		mapUrl: lease.map_url || null,
		community: lease.location_name ?? '-',
		project: lease.project_name ?? '-',
		masterProject: displayName(lease.master_project),
		dldArea: displayName(lease.dld_area),
		propertyType: lease.property_type ?? '-',
		bedrooms: lease.bedrooms ?? bedroomsMissing(lease.property_type),
		size: lease.size_sqft ?? null,
		annualRent: lease.annual_rent_aed ?? null,
		contractAmount: lease.contract_amount_aed ?? null,
		termMonths: lease.term_months ?? null,
		contractType: lease.contract_type ?? '-'
	}
}
