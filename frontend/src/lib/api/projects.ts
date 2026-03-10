import { http } from './client'

export interface GeoPolygon {
	coordinates: Array<[number, number]>
}

export interface GeoPin {
	building_name: string
	project_name: string
	latitude: number
	longitude: number
	property_id?: number
}

export type SearchSelection =
	| { type: 'master'; masterName: string }
	| { type: 'project'; projectId: number }

export interface MasterProjectSummary {
	project_id: number
	project_name: string
	project_status: string | null
	percent_completed: number | null
	no_of_buildings: number | null
	no_of_units: number | null
}

export interface MasterProjectResponse {
	master_name: string
	area_name: string
	developer_name: string | null
	total_projects: number
	total_buildings: number
	total_units: number
	projects: MasterProjectSummary[]
	geo_pins: GeoPin[]
	unit_composition: UnitComposition[]
}

export interface BuildingInfo {
	property_id: number
	building_number: string | null
	building_name: string | null
	floors: number | null
}

export interface ProjectSearchResult {
	project_id: number
	project_name: string
	area_name: string
	developer_name: string | null
	master_project_en: string | null
	latitude: number
	longitude: number
}

export interface BuildingUnitType {
	rooms_en: string
	count: number
	percentage: number
	avg_area_sqm: number | null
}

export interface BuildingDetailResponse {
	property_id: number
	building_number: string | null
	floors: number | null
	project_id: number
	project_name: string
	area_name: string
	total_units: number
	unit_composition: BuildingUnitType[]
}

export interface UnitComposition {
	property_sub_type: string
	count: number
	percentage: number
	avg_area_sqm: number | null
}

export interface ProjectDetailResponse {
	project_id: number
	project_name: string
	project_number: number | null
	master_project_en: string | null
	area_id: number
	area_name: string
	developer_id: number | null
	developer_name: string | null
	master_developer_id: number | null
	master_developer_name: string | null
	latitude: number
	longitude: number
	area_polygon: GeoPolygon | null
	no_of_buildings: number | null
	no_of_units: number | null
	no_of_villas: number | null
	no_of_lands: number | null
	project_start_date: string | null
	project_end_date: string | null
	completion_date: string | null
	percent_completed: number | null
	project_status: string | null
	unit_composition: UnitComposition[]
	buildings: BuildingInfo[]
	geo_pins: GeoPin[]
}

export const projects = {
	list: (): Promise<ProjectSearchResult[]> => http.get(`/api/v1/projects/list`),
	getDetails: (id: number): Promise<ProjectDetailResponse> => http.get(`/api/v1/projects/${id}`),
	getMaster: (name: string): Promise<MasterProjectResponse> =>
		http.get(`/api/v1/projects/master?name=${encodeURIComponent(name)}`),
	getBuilding: (propertyId: number): Promise<BuildingDetailResponse> =>
		http.get(`/api/v1/projects/building/${propertyId}`)
}
