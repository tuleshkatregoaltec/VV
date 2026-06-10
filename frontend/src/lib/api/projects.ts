import { client } from './client'
import type {
	BuildingDetailResponse,
	BuildingInfo,
	BuildingUnitType,
	DdaOutlineFeature,
	DdaPlotFeature,
	GeoPin,
	GeoPolygon,
	MasterProjectResponse,
	MasterProjectSummary,
	ProjectDetailResponse,
	ProjectRadarArea,
	ProjectRadarOverviewResponse,
	ProjectRadarProject,
	ProjectRadarResponse,
	ProjectRadarStats,
	ProjectSearchResult,
	ProjectUnitComposition
} from './generated/hey-api/types.gen'

export type {
	BuildingDetailResponse,
	BuildingInfo,
	BuildingUnitType,
	DdaOutlineFeature,
	DdaPlotFeature,
	GeoPin,
	GeoPolygon,
	MasterProjectResponse,
	MasterProjectSummary,
	ProjectDetailResponse,
	ProjectRadarArea,
	ProjectRadarOverviewResponse,
	ProjectRadarProject,
	ProjectRadarResponse,
	ProjectRadarStats,
	ProjectSearchResult,
	ProjectUnitComposition
}

export type SearchSelection =
	| { type: 'master'; masterName: string }
	| { type: 'project'; projectId: number }

export interface DdaPlotParams {
	area?: string | null
	west?: number | null
	south?: number | null
	east?: number | null
	north?: number | null
	limit?: number
	include_valuations?: boolean
}

export interface DdaOutlineParams {
	west: number
	south: number
	east: number
	north: number
	zoom: number
	limit?: number
}

export interface RadarPinParams {
	west?: number | null
	south?: number | null
	east?: number | null
	north?: number | null
	area?: string | null
	developer?: string | null
	limit?: number
}

export const projects = {
	list: (): Promise<ProjectSearchResult[]> => client.get(`/api/v1/projects/list`),
	radar: (limit = 1400): Promise<ProjectRadarResponse> =>
		client.get(client.withQuery('/api/v1/projects/radar', { limit })),
	radarOverview: (): Promise<ProjectRadarOverviewResponse> =>
		client.get('/api/v1/projects/radar/overview'),
	radarPins: (params: RadarPinParams): Promise<ProjectRadarProject[]> =>
		client.get(client.withQuery('/api/v1/projects/radar/pins', { ...params })),
	getDetails: (id: number): Promise<ProjectDetailResponse> => client.get(`/api/v1/projects/${id}`),
	getMaster: (name: string): Promise<MasterProjectResponse> =>
		client.get(client.withQuery('/api/v1/projects/master', { name })),
	getBuilding: (propertyId: number): Promise<BuildingDetailResponse> =>
		client.get(`/api/v1/projects/building/${propertyId}`),
	ddaPlots: (params: DdaPlotParams): Promise<DdaPlotFeature[]> =>
		client.get(client.withQuery('/api/v1/projects/dda-plots', { ...params })),
	ddaOutlines: (params: DdaOutlineParams): Promise<DdaOutlineFeature[]> =>
		client.get(client.withQuery('/api/v1/projects/dda-outlines', { ...params }))
}
