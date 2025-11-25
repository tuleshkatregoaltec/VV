// src/lib/stores/transactions.svelte.ts
import { transactions as api } from '$lib/api';
import type { Transaction } from '$lib/api/types';

class TransactionStore {
    #cache = $state<Transaction[]>([]);
    #loading = $state(false);
    #totalCount = $state(0);
    
    // Debug state
    #lastRequestFilters = $state<Record<string, any>>({});
    #lastResponseLength = $state(0);
    
    get cache() { return this.#cache; }
    get loading() { return this.#loading; }
    get totalCount() { return this.#totalCount; }
    get cacheSize() { return this.#cache.length; }
    get hasMore() { return this.#cache.length < this.#totalCount; }
    
    // Debug getters
    get lastRequestFilters() { return this.#lastRequestFilters; }
    get lastResponseLength() { return this.#lastResponseLength; }
    
    async load(filters: Record<string, any>) {
        this.#loading = true;
        this.#lastRequestFilters = { ...filters }; // Store request
        
        try {
            const response = await api.sales(filters);
            this.#cache = response.transactions;
            this.#totalCount = response.total;
            this.#lastResponseLength = response.transactions.length; // Store response length
        } finally {
            this.#loading = false;
        }
    }
    
    async loadMore(filters: Record<string, any>) {
        if (this.#loading || !this.hasMore) return;
        
        this.#loading = true;
        this.#lastRequestFilters = { ...filters }; // Store request
        
        try {
            const response = await api.sales({
                ...filters,
                offset: this.#cache.length
            });
            
            this.#lastResponseLength = response.transactions.length; // Store response length
            
            // Smart merge: only add transactions not already in cache
            const existingIds = new Set(this.#cache.map(t => t.transaction_id));
            const newTransactions = response.transactions.filter(
                t => !existingIds.has(t.transaction_id)
            );
            
            this.#cache = [...this.#cache, ...newTransactions];
            this.#totalCount = response.total;
        } finally {
            this.#loading = false;
        }
    }
    
    reset() {
        this.#cache = [];
        this.#totalCount = 0;
        this.#lastRequestFilters = {};
        this.#lastResponseLength = 0;
    }
}

export const transactionStore = new TransactionStore();
