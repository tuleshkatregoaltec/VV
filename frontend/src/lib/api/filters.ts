import { api } from './client';
import type { FilterOptions } from './types';

const MASTER_PROJECTS_KEY = 'master_projects';
const HOURS = 24;

const cache = {
    get(key: string): unknown | null {
        if (typeof window === 'undefined') return null;
        const item = localStorage.getItem(key);
        if (!item) return null;
        
        const { data, time } = JSON.parse(item);
        const age = (Date.now() - time) / 3600000; // hours
        return age < HOURS ? data : null;
    },
    
    set(key: string, data: unknown) {
        if (typeof window === 'undefined') return;
        localStorage.setItem(key, JSON.stringify({ data, time: Date.now() }));
    },
    
    clear(key: string) {
        if (typeof window === 'undefined') return;
        localStorage.removeItem(key);
    }
};

function buildQuery(filters: Record<string, any>): string {
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
    async masterProjects(): Promise<string[]> {
        const cached = cache.get(MASTER_PROJECTS_KEY) as string[] | null;
        if (cached) return cached;
        
        const data = await api<string[]>('/api/v1/filters/master-projects');
        cache.set(MASTER_PROJECTS_KEY, data);
        return data;
    },
    
    async sales(filterParams: Record<string, any> = {}): Promise<FilterOptions> {
        // No caching for dynamic filter options - they depend on current filters
        const query = buildQuery(filterParams);
        return api<FilterOptions>(`/api/v1/filters/sales${query}`);
    },
    
    async rentals(filterParams: Record<string, any> = {}): Promise<FilterOptions> {
        // No caching for dynamic filter options - they depend on current filters
        const query = buildQuery(filterParams);
        return api<FilterOptions>(`/api/v1/filters/rentals${query}`);
    },
    
    clearCache: () => {
        cache.clear(MASTER_PROJECTS_KEY);
    }
};
