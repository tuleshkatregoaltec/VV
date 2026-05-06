import type { DdaOutlineFeature, DdaPlotFeature } from '$lib/api/generated/hey-api/types.gen'
import { type DdaOutlineParams, type DdaPlotParams, projects } from '$lib/api/projects'

export const projectKeys = {
	all: ['projects'] as const,
	list: () => [...projectKeys.all, 'list'] as const,
	radar: (limit: number) => [...projectKeys.all, 'radar', { limit }] as const,
	master: (name: string) => [...projectKeys.all, 'master', name] as const,
	detail: (id: number) => [...projectKeys.all, 'detail', id] as const,
	building: (propertyId: number) => [...projectKeys.all, 'building', propertyId] as const,
	ddaPlots: (params: DdaPlotParams) => [...projectKeys.all, 'dda-plots', params] as const,
	ddaOutlines: (params: DdaOutlineParams) => [...projectKeys.all, 'dda-outlines', params] as const
}

export const projectQueries = {
	list: () => ({
		queryKey: projectKeys.list(),
		queryFn: () => projects.list(),
		staleTime: Infinity
	}),
	radar: (limit = 1400) => ({
		queryKey: projectKeys.radar(limit),
		queryFn: () => projects.radar(limit),
		staleTime: 30 * 60 * 1000
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
	ddaPlots: (params: DdaPlotParams | null) => ({
		queryKey: projectKeys.ddaPlots(params ?? {}),
		queryFn: () => projects.ddaPlots(params ?? {}),
		enabled: Boolean(params),
		placeholderData: (previousData: DdaPlotFeature[] | undefined) => previousData,
		staleTime: 60 * 60 * 1000
	}),
	ddaOutlines: (params: DdaOutlineParams | null) => ({
		queryKey: projectKeys.ddaOutlines(params ?? ({} as DdaOutlineParams)),
		queryFn: () => projects.ddaOutlines(params ?? ({} as DdaOutlineParams)),
		enabled: Boolean(params),
		placeholderData: (previousData: DdaOutlineFeature[] | undefined) => previousData,
		staleTime: 60 * 60 * 1000
	})
}
