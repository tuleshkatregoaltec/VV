import type { ProjectSearchItem } from '$lib/api/analytics'
import type { TransactionFilters } from '$lib/api/transactions'
import {
	DEFAULT_ITEMS_PER_PAGE,
	PROPERTY_USAGE,
	TIMEFRAME_MAPPING
} from '$lib/constants/transactions'

interface SalesLocalFilters {
	selectedBuilding: string
	selectedPropertyType: string
	selectedBedroomsOrSubType: string
	selectedRegistration: string
	areaRange: string
	priceRange: string
	pricePerSqMRange: string
}

interface RentalsLocalFilters {
	selectedPropertyType: string
	selectedPropertySubType: string
	selectedTenantType: string
	selectedRegistration: string
	areaRange: string
	rentRange: string
}

interface BaseFilterContext {
	propertyUsage: string
	timeframe: string
	currentPage: number
	selectedProject: ProjectSearchItem | null
	selectedSubProject: string | null
}

function applyProjectFilters(
	filters: TransactionFilters,
	selectedProject: ProjectSearchItem | null,
	selectedSubProject: string | null
) {
	if (selectedSubProject) {
		filters.project = selectedSubProject
		filters.filter_type = 'project'
	} else if (selectedProject) {
		filters.project = selectedProject.name
		filters.filter_type = selectedProject.filter_type
	}
}

export function buildSalesApiFilters(
	context: BaseFilterContext & { localFilters: SalesLocalFilters }
): TransactionFilters {
	const filters: TransactionFilters = {
		property_usage: context.propertyUsage,
		timeframe_days: TIMEFRAME_MAPPING[context.timeframe],
		limit: DEFAULT_ITEMS_PER_PAGE,
		offset: (context.currentPage - 1) * DEFAULT_ITEMS_PER_PAGE
	}

	applyProjectFilters(filters, context.selectedProject, context.selectedSubProject)

	if (context.localFilters.selectedBuilding !== 'All') {
		filters.building = context.localFilters.selectedBuilding
	}
	if (context.localFilters.selectedPropertyType !== 'All') {
		filters.property_type = context.localFilters.selectedPropertyType
	}
	if (context.localFilters.selectedBedroomsOrSubType !== 'All') {
		if (context.propertyUsage === PROPERTY_USAGE.RESIDENTIAL) {
			filters.rooms = context.localFilters.selectedBedroomsOrSubType
		} else {
			filters.property_sub_type = context.localFilters.selectedBedroomsOrSubType
		}
	}
	if (context.localFilters.selectedRegistration !== 'All') {
		filters.registration_type = context.localFilters.selectedRegistration
	}
	if (context.localFilters.areaRange !== 'All') {
		filters.area = context.localFilters.areaRange
	}
	if (context.localFilters.priceRange !== 'All') {
		filters.price = context.localFilters.priceRange
	}
	if (context.localFilters.pricePerSqMRange !== 'All') {
		filters.pricePerSqM = context.localFilters.pricePerSqMRange
	}

	return filters
}

export function buildSalesFilterParams(
	propertyUsage: string,
	selectedProject: ProjectSearchItem | null,
	selectedSubProject: string | null,
	selectedPropertyType: string
): Record<string, unknown> {
	const filterParams: Record<string, unknown> = {
		property_usage: propertyUsage
	}

	applyProjectFilters(filterParams, selectedProject, selectedSubProject)

	if (selectedPropertyType !== 'All') {
		filterParams.property_type = selectedPropertyType
	}

	return filterParams
}

export function buildRentalsApiFilters(
	context: BaseFilterContext & { localFilters: RentalsLocalFilters }
): TransactionFilters {
	const filters: TransactionFilters = {
		property_usage: context.propertyUsage,
		timeframe_days: TIMEFRAME_MAPPING[context.timeframe],
		limit: DEFAULT_ITEMS_PER_PAGE,
		offset: (context.currentPage - 1) * DEFAULT_ITEMS_PER_PAGE
	}

	applyProjectFilters(filters, context.selectedProject, context.selectedSubProject)

	if (context.localFilters.selectedPropertyType !== 'All') {
		filters.property_type = context.localFilters.selectedPropertyType
	}
	if (context.localFilters.selectedPropertySubType !== 'All') {
		filters.property_sub_type = context.localFilters.selectedPropertySubType
	}
	if (context.localFilters.selectedTenantType !== 'All') {
		filters.tenant_type = context.localFilters.selectedTenantType
	}
	if (context.localFilters.selectedRegistration !== 'All') {
		filters.contract_reg_type = context.localFilters.selectedRegistration
	}
	if (context.localFilters.areaRange !== 'All') {
		filters.area = context.localFilters.areaRange
	}
	if (context.localFilters.rentRange !== 'All') {
		filters.rent = context.localFilters.rentRange
	}

	return filters
}

export function buildRentalsFilterParams(
	propertyUsage: string,
	selectedProject: ProjectSearchItem | null,
	selectedSubProject: string | null,
	selectedPropertyType: string
): Record<string, unknown> {
	const filterParams: Record<string, unknown> = {
		property_usage: propertyUsage
	}

	applyProjectFilters(filterParams, selectedProject, selectedSubProject)

	if (selectedPropertyType !== 'All') {
		filterParams.property_type = selectedPropertyType
	}

	return filterParams
}

export function withSelectedIds(
	filters: TransactionFilters,
	key: 'transaction_ids' | 'contract_ids',
	selectedIds: Set<string>
): TransactionFilters {
	if (selectedIds.size === 0) return filters

	return {
		...filters,
		[key]: Array.from(selectedIds).join(',')
	}
}
