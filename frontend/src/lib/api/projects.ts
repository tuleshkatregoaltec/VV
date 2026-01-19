import { http } from './client';

export interface GeoPoint {
	latitude: number;
	longitude: number;
}

export interface GeoPolygon {
	coordinates: Array<[number, number]>;
}

export interface BuildingInfo {
	property_id: number;
	building_number: string | null;
	building_name: string | null;
	floors: number | null;
	latitude: number;
	longitude: number;
}

export interface ProjectSearchResult {
	project_id: number;
	project_name: string;
	area_name: string;
	developer_name: string | null;
	latitude: number;
	longitude: number;
}

export interface UnitComposition {
	property_sub_type: string;
	count: number;
	percentage: number;
	avg_area_sqm: number | null;
}

export interface ProjectDetailResponse {
	project_id: number;
	project_name: string;
	project_number: number | null;
	area_id: number;
	area_name: string;
	developer_id: number | null;
	developer_name: string | null;
	master_developer_id: number | null;
	master_developer_name: string | null;
	latitude: number;
	longitude: number;
	area_polygon: GeoPolygon | null;
	no_of_buildings: number | null;
	no_of_units: number | null;
	no_of_villas: number | null;
	no_of_lands: number | null;
	project_start_date: string | null;
	project_end_date: string | null;
	completion_date: string | null;
	percent_completed: number | null;
	project_status: string | null;
	unit_composition: UnitComposition[];
	buildings: BuildingInfo[];
}

export const projects = {
	list: (): Promise<ProjectSearchResult[]> => http.get(`/api/v1/projects/list`),

	getDetails: (id: number): Promise<ProjectDetailResponse> => http.get(`/api/v1/projects/${id}`)
};
