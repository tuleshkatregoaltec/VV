import { api } from './client';

export interface FilterOptions {
	projects: string[];
	buildings: string[];
	property_types: string[];
	property_sub_types: string[];
	rooms: string[];
	registration_types: string[];
	tenant_types?: string[];
	contract_reg_types?: string[];
}

export interface FilterParams {
	property_usage?: string;
	project?: string;
	filter_type?: string;
	property_type?: string;
	area?: string;
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
	sales: (filterParams: FilterParams = {}) => {
		const query = buildQuery(filterParams);
		return api<FilterOptions>(`/api/v1/filters/sales${query}`);
	},

	rentals: (filterParams: FilterParams = {}) => {
		const query = buildQuery(filterParams);
		return api<FilterOptions>(`/api/v1/filters/rentals${query}`);
	}
};
