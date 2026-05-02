import { client } from './client'
import type {
	BuildingDetailResponse,
	BuildingInfo,
	BuildingUnitType,
	DdaPlotFeature,
	GeoPin,
	GeoPolygon,
	MasterProjectResponse,
	MasterProjectSummary,
	ProjectDetailResponse,
	ProjectSearchResult,
	ProjectUnitComposition
} from './generated/hey-api/types.gen'

export type {
	BuildingDetailResponse,
	BuildingInfo,
	BuildingUnitType,
	DdaPlotFeature,
	GeoPin,
	GeoPolygon,
	MasterProjectResponse,
	MasterProjectSummary,
	ProjectDetailResponse,
	ProjectSearchResult,
	ProjectUnitComposition
}

export type SearchSelection =
	| { type: 'master'; masterName: string }
	| { type: 'project'; projectId: number }

export const projects = {
	list: (): Promise<ProjectSearchResult[]> => client.get(`/api/v1/projects/list`),
	getDetails: (id: number): Promise<ProjectDetailResponse> => client.get(`/api/v1/projects/${id}`),
	getMaster: (name: string): Promise<MasterProjectResponse> =>
		client.get(client.withQuery('/api/v1/projects/master', { name })),
	getBuilding: (propertyId: number): Promise<BuildingDetailResponse> =>
		client.get(`/api/v1/projects/building/${propertyId}`),
	ddaPlots: (area: string): Promise<DdaPlotFeature[]> =>
		client.get(client.withQuery('/api/v1/projects/dda-plots', { area }))
}
