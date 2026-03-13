import { feasibility } from '$lib/api/feasibility'

export const feasibilityKeys = {
	all: ['feasibility'] as const,
	areas: () => [...feasibilityKeys.all, 'areas'] as const,
	communities: () => [...feasibilityKeys.all, 'communities'] as const
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
	})
}
