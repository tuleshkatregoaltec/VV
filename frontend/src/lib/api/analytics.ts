// src/lib/api/analytics.ts
import { api } from './client'

export type TimeframeDays = 7 | 30 | 90 | 180 | 365

export interface AnalyticsSummary {
	transaction_count: number
	total_volume: number
	avg_price: number
	avg_price_sqft: number
	min_price: number
	max_price: number
	volume_change_pct: number | null
	count_change_pct: number | null
}

export interface RentalSummary {
	contract_count: number
	total_annual_value: number
	avg_annual_rent: number
	avg_rent_sqft: number
	min_annual_rent: number
	max_annual_rent: number
	value_change_pct: number | null
	count_change_pct: number | null
}

export interface DimensionBreakdown {
	dimension_value: string
	transaction_count: number
	total_volume: number
	avg_price_sqft: number
	pct_of_total: number | null
}

export interface RentalDimensionBreakdown {
	dimension_value: string
	contract_count: number
	total_annual_value: number
	avg_rent_sqft: number
	pct_of_total: number | null
}

export interface TrendPoint {
	date: string
	count: number
	total_value: number
	avg_value: number
	avg_sqft: number
}

export interface SalesAnalyticsResponse {
	timeframe_days: number
	property_usage: string
	summary: AnalyticsSummary
	trends: TrendPoint[]
	by_property_type: DimensionBreakdown[]
	by_rooms: DimensionBreakdown[]
	by_reg_type: DimensionBreakdown[]
	by_master_project: DimensionBreakdown[]
}

export interface RentalAnalyticsResponse {
	timeframe_days: number
	property_usage: string
	summary: RentalSummary
	trends: TrendPoint[]
	by_property_type: RentalDimensionBreakdown[]
	by_master_project: RentalDimensionBreakdown[]
}

export interface AnalyticsParams {
	property_usage?: string
	timeframe_days?: TimeframeDays
	start_date?: string
	end_date?: string
	property_type?: string
	rooms?: string
	reg_type?: string
	price_bucket?: string
	area_bucket?: string
}

export interface RentalAnalyticsParams {
	property_usage?: string
	timeframe_days?: TimeframeDays
	start_date?: string
	end_date?: string
	property_type?: string
	rent_bucket?: string
	area_bucket?: string
}

function buildQuery(params: AnalyticsParams | RentalAnalyticsParams): string {
	const query = new URLSearchParams()

	// Basic filters
	if (params.property_usage) query.append('property_usage', params.property_usage)

	// Date range filters (prefer explicit dates over timeframe_days)
	if (params.start_date) query.append('start_date', params.start_date)
	if (params.end_date) query.append('end_date', params.end_date)
	if (params.timeframe_days && !params.start_date) {
		query.append('timeframe_days', String(params.timeframe_days))
	}

	// Dimension filters
	if (params.property_type) query.append('property_type', params.property_type)
	if (params.area_bucket) query.append('area_bucket', params.area_bucket)

	// Sales-specific filters
	if ('rooms' in params && params.rooms) {
		query.append('rooms', params.rooms)
	}
	if ('reg_type' in params && params.reg_type) {
		query.append('reg_type', params.reg_type)
	}
	if ('price_bucket' in params && params.price_bucket) {
		query.append('price_bucket', params.price_bucket)
	}

	// Rental-specific filters
	if ('rent_bucket' in params && params.rent_bucket) {
		query.append('rent_bucket', params.rent_bucket)
	}

	return query.toString()
}

export interface MarketTrendPoint {
	date: string
	transaction_count: number
	avg_price: number
	avg_price_sqm: number
}

export interface MarketTrendResponse {
	data: MarketTrendPoint[]
	total_transactions: number
	avg_price_change_pct: number | null
	avg_price_sqm_change_pct: number | null
}

// =============================================================================
// PROJECT ANALYTICS TYPES
// =============================================================================

export interface ProjectMeta {
	project_name: string
	area_name: string | null
	developer_name: string | null
	project_status: string | null
	completion_date: string | null
	percent_completed: number | null
	no_of_units: number | null
	no_of_buildings: number | null
}

export interface ProjectSalesSummary {
	transaction_count: number
	total_volume: number
	avg_price: number
	avg_price_sqm: number
	median_price: number
}

export interface ProjectRentalSummary {
	contract_count: number
	total_annual_value: number
	median_annual_rent: number
	median_rent_sqm: number
}

export interface RoomAnalytics {
	rooms: string
	sale_count: number
	avg_sale_price: number
	avg_sale_price_sqm: number
	rental_count: number
	median_annual_rent: number
	median_rent_sqm: number
	gross_yield_pct: number | null
}

export interface PropertyTypeBreakdown {
	property_type: string
	count: number
	avg_price: number
	pct_of_total: number
}

export interface RegTypeBreakdown {
	reg_type: string
	count: number
	avg_price: number
	pct_of_total: number
}

export interface UnitComposition {
	rooms: string
	count: number
	pct_of_total: number
}

export interface ProjectAnalyticsResponse {
	project: ProjectMeta | null
	sales: ProjectSalesSummary
	rentals: ProjectRentalSummary
	overall_gross_yield_pct: number | null
	by_rooms: RoomAnalytics[]
	by_property_type: PropertyTypeBreakdown[]
	by_reg_type: RegTypeBreakdown[]
	unit_composition: UnitComposition[]
}

export interface ProjectTrendPoint {
	date: string
	transaction_count: number
	avg_price: number
	avg_price_sqm: number
}

export interface ProjectTrendsResponse {
	data: ProjectTrendPoint[]
}

export interface ProjectSearchItem {
	name: string
	filter_type: 'master' | 'virtual_master' | 'project'
}

export interface ProjectSearchResponse {
	projects: ProjectSearchItem[]
}

export interface SubProjectItem {
	name: string
	transaction_count: number
}

export interface SubProjectsResponse {
	sub_projects: SubProjectItem[]
}

export const analytics = {
	sales: (params: AnalyticsParams = {}) =>
		api<SalesAnalyticsResponse>(`/api/v1/analytics/sales?${buildQuery(params)}`),

	rentals: (params: RentalAnalyticsParams = {}) =>
		api<RentalAnalyticsResponse>(`/api/v1/analytics/rentals?${buildQuery(params)}`),

	marketTrend: (params: { days: number; property_usage?: string } = { days: 180 }) => {
		const q = new URLSearchParams({ days: String(params.days) })
		if (params.property_usage) q.append('property_usage', params.property_usage)
		return api<MarketTrendResponse>(`/api/v1/analytics/market-trend?${q}`)
	},

	projectSearch: (search = '', limit = 50) => {
		const q = new URLSearchParams({ search, limit: String(limit) })
		return api<ProjectSearchResponse>(`/api/v1/analytics/projects?${q}`)
	},

	subProjects: (masterProject: string, filterType: string = 'master') => {
		const q = new URLSearchParams({ master_project: masterProject, filter_type: filterType })
		return api<SubProjectsResponse>(`/api/v1/analytics/project/sub-projects?${q}`)
	},

	projectSummary: (params: { masterProject?: string; project?: string; filterType?: string }) => {
		const q = new URLSearchParams()
		if (params.project) q.set('project', params.project)
		if (params.masterProject) q.set('master_project', params.masterProject)
		if (params.filterType) q.set('filter_type', params.filterType)
		return api<ProjectAnalyticsResponse>(`/api/v1/analytics/project/summary?${q}`)
	},

	projectTrends: (
		params: { masterProject?: string; project?: string; filterType?: string },
		days = 365
	) => {
		const q = new URLSearchParams({ days: String(days) })
		if (params.project) q.set('project', params.project)
		if (params.masterProject) q.set('master_project', params.masterProject)
		if (params.filterType) q.set('filter_type', params.filterType)
		return api<ProjectTrendsResponse>(`/api/v1/analytics/project/trends?${q}`)
	}
}
