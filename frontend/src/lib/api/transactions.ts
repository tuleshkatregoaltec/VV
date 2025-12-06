// src/lib/api/transactions.ts
import { api } from './client';
import type { TransactionListResponse, RentalContractListResponse } from './types';

function buildQuery(filters: Record<string, any>): string {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== 'All') {
            params.append(k, String(v));
        }
    });
    return params.toString();
}

export const transactions = {
    sales: (filters: Record<string, any>) => 
        api<TransactionListResponse>(`/api/v1/transactions/sales?${buildQuery(filters)}`),
    
    rentals: (filters: Record<string, any>) => 
        api<RentalContractListResponse>(`/api/v1/transactions/rentals?${buildQuery(filters)}`),
};
