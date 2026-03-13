import { analytics, type TimeframeDays } from '$lib/api/analytics'

export const analyticsKeys = {
	all: ['analytics'] as const,
	marketTrend: (days: number, propertyUsage?: string) =>
		[...analyticsKeys.all, 'marketTrend', { days, propertyUsage }] as const,
	projectSearch: (search: string, limit: number) =>
		[...analyticsKeys.all, 'projectSearch', { search, limit }] as const,
	subProjects: (masterProject: string, filterType: string) =>
		[...analyticsKeys.all, 'subProjects', { masterProject, filterType }] as const,
	projectSummary: (params: { masterProject?: string; project?: string; filterType?: string }) =>
		[...analyticsKeys.all, 'projectSummary', params] as const,
	projectTrends: (
		params: { masterProject?: string; project?: string; filterType?: string },
		days: number
	) => [...analyticsKeys.all, 'projectTrends', params, days] as const
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
		staleTime: search === '' ? Infinity : 5 * 60 * 1000
	}),
	subProjects: (masterProject: string | null, filterType: string | null) => ({
		queryKey: analyticsKeys.subProjects(masterProject ?? '', filterType ?? ''),
		queryFn: () => analytics.subProjects(masterProject ?? '', filterType ?? 'master'),
		enabled: Boolean(masterProject && filterType && filterType !== 'project'),
		staleTime: Infinity
	}),
	projectSummary: (params: { masterProject?: string; project?: string; filterType?: string }) => ({
		queryKey: analyticsKeys.projectSummary(params),
		queryFn: () => analytics.projectSummary(params),
		staleTime: 5 * 60 * 1000
	}),
	projectTrends: (
		params: { masterProject?: string; project?: string; filterType?: string },
		days = 365
	) => ({
		queryKey: analyticsKeys.projectTrends(params, days),
		queryFn: () => analytics.projectTrends(params, days),
		staleTime: 5 * 60 * 1000
	})
}

export interface SalesTransactionQueryParams {
	property_usage?: string
	timeframe_days?: TimeframeDays | number
	project?: string
	filter_type?: string
	building?: string
	property_type?: string
	rooms?: string
	property_sub_type?: string
	registration_type?: string
	area?: string
	price?: string
	pricePerSqM?: string
	limit?: number
	offset?: number
}
