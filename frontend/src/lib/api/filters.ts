import { api } from './client';

export interface FilterOptions {
	projects: string[];
	buildings: string[];
	property_types: string[];
	property_sub_types: string[];
	master_projects: string[];
	rooms: string[];
	registration_types: string[];
	tenant_types?: string[];
	contract_reg_types?: string[];
}

export interface FilterParams {
	property_usage?: string;
	timeframe_days?: number;
	master_project?: string;
	project?: string;
	building?: string;
	property_type?: string;
	rooms?: string;
	registration_type?: string;
}

function buildQuery(filters: FilterParams): string {
	const params = new URLSearchParams();
	Object.entries(filters).forEach(([k, v]) => {
		if (v !== undefined && v !== null && v !== 'All') {
			params.append(k, String(v));
		}
	});
	const qs = params.toString();
	return qs ? `?${qs}` : '';
}

export const filters = {
	masterProjects: () => api<string[]>('/api/v1/filters/master-projects'),

	sales: (filterParams: FilterParams = {}) => {
		const query = buildQuery(filterParams);
		return api<FilterOptions>(`/api/v1/filters/sales${query}`);
	},

	rentals: (filterParams: FilterParams = {}) => {
		const query = buildQuery(filterParams);
		return api<FilterOptions>(`/api/v1/filters/rentals${query}`);
	}
};
