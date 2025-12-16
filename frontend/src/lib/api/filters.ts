import { api } from './client';
import type { FilterOptions } from './types';

function buildQuery(filters: Record<string, any>): string {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== 'All') {
            params.append(k, String(v));  // Just pass as-is, no normalization
        }
    });
    const qs = params.toString();
    return qs ? `?${qs}` : '';
}

export const filters = {
    masterProjects: (): Promise<string[]> => {
        return api<string[]>('/api/v1/filters/master-projects');
    },
    
    sales: (filterParams: Record<string, any> = {}): Promise<FilterOptions> => {
        const query = buildQuery(filterParams);
        return api<FilterOptions>(`/api/v1/filters/sales${query}`);
    },
    
    rentals: (filterParams: Record<string, any> = {}): Promise<FilterOptions> => {
        const query = buildQuery(filterParams);
        return api<FilterOptions>(`/api/v1/filters/rentals${query}`);
    }
};
