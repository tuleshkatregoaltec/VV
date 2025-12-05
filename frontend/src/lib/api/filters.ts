import { api } from './client';
import type { FilterOptions } from './types';

const CACHE_KEY = 'filters';
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

export const filters = {
    async masterProjects(): Promise<string[]> {
        const cached = cache.get(MASTER_PROJECTS_KEY) as string[] | null;
        if (cached) return cached;
        
        const data = await api<string[]>('/filters/master-projects');
        cache.set(MASTER_PROJECTS_KEY, data);
        return data;
    },
    
    async sales(query = ''): Promise<FilterOptions> {
        const cached = cache.get(CACHE_KEY) as FilterOptions | null;
        if (cached) return cached;
        
        const data = await api<FilterOptions>(`/filters/sales${query}`);
        cache.set(CACHE_KEY, data);
        return data;
    },
    
    async rentals(query = ''): Promise<FilterOptions> {
        const cached = cache.get(CACHE_KEY) as FilterOptions | null;
        if (cached) return cached;
        
        const data = await api<FilterOptions>(`/filters/rentals${query}`);
        cache.set(CACHE_KEY, data);
        return data;
    },
    
    clearCache: () => {
        cache.clear(CACHE_KEY);
        cache.clear(MASTER_PROJECTS_KEY);
    }
};
