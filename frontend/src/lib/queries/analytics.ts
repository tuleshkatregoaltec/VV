import { analytics, type ProjectParams } from '$lib/api/analytics'

export const analyticsKeys = {
	all: ['analytics', 'dxbi-v2'] as const,
	marketTrend: (days: number, propertyUsage?: string) =>
		[...analyticsKeys.all, 'marketTrend', { days, propertyUsage }] as const,
	projectSearch: (search: string, limit: number) =>
		[...analyticsKeys.all, 'projectSearch', { search, limit }] as const,
	subProjects: (masterProject: string, filterType: string) =>
		[...analyticsKeys.all, 'subProjects', { masterProject, filterType }] as const,
	projectSummary: (params: ProjectParams) =>
		[...analyticsKeys.all, 'projectSummary', params] as const,
	projectTrends: (params: ProjectParams, days: number) =>
		[...analyticsKeys.all, 'projectTrends', params, days] as const,
	projectForecast: (params: ProjectParams, days: number) =>
		[...analyticsKeys.all, 'projectForecast', params, days] as const,
	projectPipeline: (params: ProjectParams) =>
		[...analyticsKeys.all, 'projectPipeline', params] as const,
	projectPriceDistribution: (params: ProjectParams, regType?: string) =>
		[...analyticsKeys.all, 'projectPriceDistribution', params, regType ?? 'all'] as const
}

export const analyticsQueries = {
	marketTrend: (days: number, propertyUsage?: string) => ({
		queryKey: analyticsKeys.marketTrend(days, propertyUsage),
		queryFn: () => analytics.marketTrend({ days, property_usage: propertyUsage }),
		staleTime: 5 * 60 * 1000
	}),
	projectSearch: (search = '', limit = 50) => ({
		queryKey: analyticsKeys.projectSearch(search, limit),
		queryFn: () => analytics.projectSearch(search, limit),
		staleTime: 5 * 60 * 1000
	}),
	subProjects: (masterProject: string | null, filterType: string | null) => ({
		queryKey: analyticsKeys.subProjects(masterProject ?? '', filterType ?? ''),
		queryFn: () => analytics.subProjects(masterProject ?? '', filterType ?? 'master'),
		enabled: Boolean(masterProject && filterType && !['project', 'market'].includes(filterType)),
		staleTime: 5 * 60 * 1000
	}),
	projectSummary: (params: ProjectParams) => ({
		queryKey: analyticsKeys.projectSummary(params),
		queryFn: () => analytics.projectSummary(params),
		staleTime: 5 * 60 * 1000
	}),
	projectTrends: (params: ProjectParams, days = 365) => ({
		queryKey: analyticsKeys.projectTrends(params, days),
		queryFn: () => analytics.projectTrends(params, days),
		staleTime: 5 * 60 * 1000
	}),
	projectForecast: (params: ProjectParams, days = 365) => ({
		queryKey: analyticsKeys.projectForecast(params, days),
		queryFn: () => analytics.projectForecast(params, days),
		staleTime: 5 * 60 * 1000
	}),
	projectPipeline: (params: ProjectParams) => ({
		queryKey: analyticsKeys.projectPipeline(params),
		queryFn: () => analytics.projectPipeline(params),
		staleTime: 5 * 60 * 1000
	}),
	projectPriceDistribution: (params: ProjectParams, regType?: string) => ({
		queryKey: analyticsKeys.projectPriceDistribution(params, regType),
		queryFn: () => analytics.projectPriceDistribution(params, regType),
		staleTime: 5 * 60 * 1000
	})
}
