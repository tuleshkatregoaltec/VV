import { api } from './client';
import type { TransactionListResponse, RentalContractListResponse } from './types';
import { env } from '$env/dynamic/public';

function buildQuery(filters: Record<string, any>): string {
    const params = new URLSearchParams();
    // Map dropdown string values to numeric ranges for API
    // Note: Database stores area in sq.m and price per sq.m
    const rangeMap: Record<string, Record<string, [number?, number?]>> = {
        area: {
            // Area ranges in sq.m (database stores sqm)
            '<50': [0, 50],
            '50-100': [50, 100],
            '100-200': [100, 200],
            '200-500': [200, 500],
            '>500': [500, 10000000],
        },
        price: {
            '<500k': [0, 500000],
            '500k-1M': [500000, 1000000],
            '1M-2M': [1000000, 2000000],
            '2M-5M': [2000000, 5000000],
            '>5M': [5000000, 9999999999],
        },
        pricePerSqM: {
            // Price per sq.m ranges (database stores price/sqm, typical 15000-35000 AED/sqm)
            '<10000': [0, 10000],
            '10000-20000': [10000, 20000],
            '20000-30000': [20000, 30000],
            '>30000': [30000, 9999999],
        },
        // Legacy support for pricePerSqFt (maps to pricePerSqM on backend)
        pricePerSqFt: {
            '<10000': [0, 10000],
            '10000-20000': [10000, 20000],
            '20000-30000': [20000, 30000],
            '>30000': [30000, 9999999],
        },
        annualRent: {
            '<50k': [0, 50000],
            '50k-100k': [50000, 100000],
            '100k-200k': [100000, 200000],
            '>200k': [200000, 999999999],
        },
    };

    Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== 'All') {
            // Special handling for transaction_ids and contract_ids - pass through as-is
            if (k === 'transaction_ids' || k === 'contract_ids') {
                params.append(k, String(v));
            } else if (rangeMap[k] && typeof v === 'string' && rangeMap[k][v]) {
                const [min, max] = rangeMap[k][v];
                if (min !== undefined) params.append(`${k}_min`, String(min));
                if (max !== undefined) params.append(`${k}_max`, String(max));
            } else {
                params.append(k, String(v));
            }
        }
    });
    return params.toString();
}

export const transactions = {
    sales: (filters: Record<string, any>) => 
        api<TransactionListResponse>(`/api/v1/transactions/sales?${buildQuery(filters)}`),
    
    rentals: (filters: Record<string, any>) => 
        api<RentalContractListResponse>(`/api/v1/transactions/rentals?${buildQuery(filters)}`),
    
    // Export functions - return blob URLs for download
    exportSales: async (filters: Record<string, any>): Promise<Blob> => {
        const response = await fetch(
            `${env.PUBLIC_API_BASE_URL}/api/v1/transactions/sales/export?${buildQuery(filters)}`,
            { credentials: 'include' }
        );
        
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Export failed: ${response.status} - ${text}`);
        }
        
        return response.blob();
    },
    
    exportRentals: async (filters: Record<string, any>): Promise<Blob> => {
        const response = await fetch(
            `${env.PUBLIC_API_BASE_URL}/api/v1/transactions/rentals/export?${buildQuery(filters)}`,
            { credentials: 'include' }
        );
        
        if (!response.ok) {
            const text = await response.text();
            throw new Error(`Export failed: ${response.status} - ${text}`);
        }
        
        return response.blob();
    }
};
