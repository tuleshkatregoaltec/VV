import { api } from './client';
import type { FilterOptions } from './types';

const CACHE_KEY = 'filters';
const HOURS = 24;

const cache = {
    get(): FilterOptions | null {
        if (typeof window === 'undefined') return null;
        const item = localStorage.getItem(CACHE_KEY);
        if (!item) return null;
        
        const { data, time } = JSON.parse(item);
        const age = (Date.now() - time) / 3600000; // hours
        return age < HOURS ? data : null;
    },
    
    set(data: FilterOptions) {
        if (typeof window === 'undefined') return;
        localStorage.setItem(CACHE_KEY, JSON.stringify({ data, time: Date.now() }));
    },
    
    clear() {
        if (typeof window === 'undefined') return;
        localStorage.removeItem(CACHE_KEY);
    }
};

export const filters = {
    async sales(query = ''): Promise<FilterOptions> {
        const cached = cache.get();
        if (cached) return cached;
        
        const data = await api<FilterOptions>(`/transactions/sales/filter-options${query}`);
        cache.set(data);
        return data;
    },
    
    async rentals(query = ''): Promise<FilterOptions> {
        const cached = cache.get();
        if (cached) return cached;
        
        const data = await api<FilterOptions>(`/transactions/rentals/filter-options${query}`);
        cache.set(data);
        return data;
    },
    
    clearCache: () => cache.clear()
};
