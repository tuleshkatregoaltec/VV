import { feasibility } from '$lib/api/feasibility'

export const feasibilityKeys = {
	all: ['feasibility'] as const,
	areas: () => [...feasibilityKeys.all, 'areas'] as const,
	communities: () => [...feasibilityKeys.all, 'communities'] as const,
	searchPlots: (params: {
		q?: string
		community?: string
		minPlotAreaSqm?: number
		maxPlotAreaSqm?: number
		offset?: number
		limit?: number
	}) => [...feasibilityKeys.all, 'searchPlots', params] as const,
	communityPlots: (community: string, pageSize: number) =>
		[...feasibilityKeys.all, 'communityPlots', community, pageSize] as const,
	plotData: (plotNumber: string) => [...feasibilityKeys.all, 'plotData', plotNumber] as const,
	generateStudy: (plotNumber: string, usageOverride?: string) =>
		[...feasibilityKeys.all, 'generateStudy', plotNumber, usageOverride] as const
}

export const feasibilityQueries = {
	areas: () => ({
		queryKey: feasibilityKeys.areas(),
		queryFn: () => feasibility.getAreas(),
		staleTime: Infinity
	}),
	communities: () => ({
		queryKey: feasibilityKeys.communities(),
		queryFn: () => feasibility.getCommunities(),
		staleTime: Infinity
	}),
	searchPlots: (params: {
		q?: string
		community?: string
		minPlotAreaSqm?: number
		maxPlotAreaSqm?: number
		offset?: number
		limit?: number
	}) => ({
		queryKey: feasibilityKeys.searchPlots(params),
		queryFn: () => feasibility.searchPlots(params),
		staleTime: 5 * 60 * 1000
	}),
	communityPlots: (community: string | null, pageSize = 100) => ({
		queryKey: feasibilityKeys.communityPlots(community ?? '', pageSize),
		queryFn: () => {
			if (!community) throw new Error('community is required')
			return feasibility.searchAllCommunityPlots(community, pageSize)
		},
		enabled: Boolean(community),
		staleTime: 5 * 60 * 1000
	}),
	plotData: (plotNumber: string | null) => ({
		queryKey: feasibilityKeys.plotData(plotNumber ?? ''),
		queryFn: () => {
			if (!plotNumber) throw new Error('plotNumber is required')
			return feasibility.getPlotData(plotNumber)
		},
		enabled: Boolean(plotNumber),
		staleTime: Infinity
	}),
	generateStudy: (
		plotNumber: string | null,
		usageOverride?: 'residential' | 'commercial' | 'mixed_use' | 'unknown'
	) => ({
		queryKey: feasibilityKeys.generateStudy(plotNumber ?? '', usageOverride),
		queryFn: () => {
			if (!plotNumber) throw new Error('plotNumber is required')
			return feasibility.generateStudy({ plot_number: plotNumber, usage_override: usageOverride })
		},
		enabled: Boolean(plotNumber),
		staleTime: Infinity
	})
}
