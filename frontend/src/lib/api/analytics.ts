import { client } from './client'
import type {
	AnalyticsGetRentalAnalyticsData,
	AnalyticsGetSalesAnalyticsData,
	AnalyticsResponse,
	AnalyticsSummary,
	AnalyticsUnitComposition,
	DimensionBreakdown,
	MarketTrendResponse,
	PriceDistributionBucket,
	ProjectAnalyticsResponse,
	ProjectConfigurationRow,
	ProjectForecastPoint,
	ProjectForecastResponse,
	ProjectMeta,
	ProjectPipelinePoint,
	ProjectPipelineResponse,
	ProjectPriceDistributionResponse,
	ProjectRentalSummary,
	ProjectSalesSummary,
	ProjectSearchItem,
	ProjectSearchResponse,
	ProjectTrendPoint,
	ProjectTrendsResponse,
	PropertyTypeBreakdown,
	RegTypeBreakdown,
	RentalAnalyticsResponse,
	RentalDimensionBreakdown,
	RentalSummary,
	RoomAnalytics,
	SubProjectItem,
	SubProjectsResponse,
	TrendPoint
} from './generated/hey-api/types.gen'

export type TimeframeDays = 7 | 30 | 90 | 180 | 365
export type SalesAnalyticsResponse = AnalyticsResponse
export type {
	AnalyticsSummary,
	DimensionBreakdown,
	PriceDistributionBucket,
	ProjectAnalyticsResponse,
	ProjectMeta,
	ProjectConfigurationRow,
	ProjectForecastPoint,
	ProjectForecastResponse,
	ProjectPipelinePoint,
	ProjectPipelineResponse,
	ProjectPriceDistributionResponse,
	ProjectRentalSummary,
	ProjectSalesSummary,
	ProjectSearchItem,
	ProjectTrendPoint,
	PropertyTypeBreakdown,
	RegTypeBreakdown,
	RentalDimensionBreakdown,
	RentalSummary,
	RoomAnalytics,
	SubProjectItem,
	TrendPoint,
	AnalyticsUnitComposition
}
export type AnalyticsParams = NonNullable<AnalyticsGetSalesAnalyticsData['query']> & {
	timeframe_days?: TimeframeDays | null
}
export type RentalAnalyticsParams = NonNullable<AnalyticsGetRentalAnalyticsData['query']> & {
	timeframe_days?: TimeframeDays | null
}

// Which records a project view covers: Residential or Commercial, or auto (Commercial for a scope
// with no residential records).
export type AnalyticsUsage = 'auto' | 'Residential' | 'Commercial'

export type ProjectParams = {
	masterProject?: string
	project?: string
	filterType?: string
	// A building scope: the id the search returned (overrides project and master).
	buildingId?: string
	usage?: AnalyticsUsage
}

export const analytics = {
	sales: (params: AnalyticsParams = {}) =>
		client.get<SalesAnalyticsResponse>(client.withQuery('/api/v1/analytics/sales', params)),

	rentals: (params: RentalAnalyticsParams = {}) =>
		client.get<RentalAnalyticsResponse>(client.withQuery('/api/v1/analytics/rentals', params)),

	marketTrend: (params: { days: number; property_usage?: string } = { days: 180 }) =>
		client.get<MarketTrendResponse>(client.withQuery('/api/v1/analytics/market-trend', params)),

	projectSearch: (search = '', limit = 50) =>
		client.get<ProjectSearchResponse>(
			client.withQuery('/api/v1/analytics/projects', { search, limit })
		),

	subProjects: (masterProject: string, filterType: string = 'master') =>
		client.get<SubProjectsResponse>(
			client.withQuery('/api/v1/analytics/project/sub-projects', {
				master_project: masterProject,
				filter_type: filterType
			})
		),

	projectSummary: (params: ProjectParams) =>
		client.get<ProjectAnalyticsResponse>(
			client.withQuery('/api/v1/analytics/project/summary', {
				project: params.project,
				master_project: params.masterProject,
				building_id: params.buildingId,
				filter_type: params.filterType,
				usage: params.usage
			})
		),

	projectTrends: (params: ProjectParams, days = 365) =>
		client.get<ProjectTrendsResponse>(
			client.withQuery('/api/v1/analytics/project/trends', {
				days,
				project: params.project,
				master_project: params.masterProject,
				building_id: params.buildingId,
				filter_type: params.filterType,
				usage: params.usage
			})
		),

	projectForecast: (params: ProjectParams, days = 365) =>
		client.get<ProjectForecastResponse>(
			client.withQuery('/api/v1/analytics/project/forecast', {
				days,
				project: params.project,
				master_project: params.masterProject,
				building_id: params.buildingId,
				filter_type: params.filterType
			})
		),

	projectPipeline: (params: ProjectParams) =>
		client.get<ProjectPipelineResponse>(
			client.withQuery('/api/v1/analytics/project/pipeline', {
				project: params.project,
				master_project: params.masterProject,
				building_id: params.buildingId,
				filter_type: params.filterType
			})
		),

	projectPriceDistribution: (params: ProjectParams, regType?: string) =>
		client.get<ProjectPriceDistributionResponse>(
			client.withQuery('/api/v1/analytics/project/price-distribution', {
				project: params.project,
				master_project: params.masterProject,
				building_id: params.buildingId,
				filter_type: params.filterType,
				usage: params.usage,
				reg_type: regType
			})
		)
}
