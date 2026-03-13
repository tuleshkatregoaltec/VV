import { filters } from '$lib/api/filters'
import type { RentalContractListResponse, TransactionListResponse } from '$lib/api/transactions'
import { type TransactionFilters, transactions } from '$lib/api/transactions'

export const transactionKeys = {
	all: ['transactions'] as const,
	sales: (params: TransactionFilters) => [...transactionKeys.all, 'sales', params] as const,
	rentals: (params: TransactionFilters) => [...transactionKeys.all, 'rentals', params] as const,
	filterOptions: (kind: 'sales' | 'rentals', params: Record<string, unknown>) =>
		[...transactionKeys.all, 'filterOptions', kind, params] as const
}

export const transactionQueries = {
	sales: (params: TransactionFilters) => ({
		queryKey: transactionKeys.sales(params),
		queryFn: () => transactions.sales(params),
		placeholderData: (previousData: TransactionListResponse | undefined) => previousData
	}),
	rentals: (params: TransactionFilters) => ({
		queryKey: transactionKeys.rentals(params),
		queryFn: () => transactions.rentals(params),
		placeholderData: (previousData: RentalContractListResponse | undefined) => previousData
	}),
	salesFilterOptions: (params: Record<string, unknown>) => ({
		queryKey: transactionKeys.filterOptions('sales', params),
		queryFn: () => filters.sales(params),
		staleTime: 5 * 60 * 1000
	}),
	rentalFilterOptions: (params: Record<string, unknown>) => ({
		queryKey: transactionKeys.filterOptions('rentals', params),
		queryFn: () => filters.rentals(params),
		staleTime: 5 * 60 * 1000
	})
}
