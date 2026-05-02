import { projects } from '$lib/api/projects'

export const projectKeys = {
	all: ['projects'] as const,
	list: () => [...projectKeys.all, 'list'] as const,
	master: (name: string) => [...projectKeys.all, 'master', name] as const,
	detail: (id: number) => [...projectKeys.all, 'detail', id] as const,
	building: (propertyId: number) => [...projectKeys.all, 'building', propertyId] as const,
	ddaPlots: (area: string) => [...projectKeys.all, 'dda-plots', area] as const
}

export const projectQueries = {
	list: () => ({
		queryKey: projectKeys.list(),
		queryFn: () => projects.list(),
		staleTime: Infinity
	}),
	master: (name: string | null) => ({
		queryKey: projectKeys.master(name ?? ''),
		queryFn: () => projects.getMaster(name ?? ''),
		enabled: Boolean(name),
		staleTime: 10 * 60 * 1000
	}),
	detail: (id: number | null) => ({
		queryKey: projectKeys.detail(id ?? 0),
		queryFn: () => projects.getDetails(id ?? 0),
		enabled: id !== null,
		staleTime: 10 * 60 * 1000
	}),
	building: (propertyId: number | null) => ({
		queryKey: projectKeys.building(propertyId ?? 0),
		queryFn: () => projects.getBuilding(propertyId ?? 0),
		enabled: propertyId !== null,
		staleTime: 10 * 60 * 1000
	}),
	ddaPlots: (area: string | null) => ({
		queryKey: projectKeys.ddaPlots(area ?? ''),
		queryFn: () => projects.ddaPlots(area ?? ''),
		enabled: Boolean(area),
		staleTime: 60 * 60 * 1000
	})
}
