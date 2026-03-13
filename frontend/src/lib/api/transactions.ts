import { client } from './client'
import type {
	RentalContractListResponse,
	RentalContractResponseOutput,
	TransactionListResponse,
	TransactionResponseOutput
} from './generated/hey-api/types.gen'

export type {
	RentalContractListResponse,
	RentalContractResponseOutput,
	TransactionListResponse,
	TransactionResponseOutput
}

export interface TransactionFilters {
	trans_group?: string
	property_usage?: string
	timeframe_days?: number
	project?: string
	filter_type?: string
	building?: string
	property_type?: string
	rooms?: string
	property_sub_type?: string
	tenant_type?: string
	registration_type?: string
	contract_reg_type?: string
	area?: string
	area_min?: number
	area_max?: number
	price?: string
	price_min?: number
	price_max?: number
	pricePerSqM?: string
	pricePerSqFt?: string
	price_sqft_min?: number
	price_sqft_max?: number
	annualRent?: string
	rent?: string
	transaction_ids?: string
	contract_ids?: string
	limit?: number
	offset?: number
}

function buildQuery(filters: TransactionFilters): string {
	const params = new URLSearchParams()
	const rangeMap: Record<string, Record<string, [number?, number?]>> = {
		area: {
			'<50': [0, 50],
			'50-100': [50, 100],
			'100-200': [100, 200],
			'200-500': [200, 500],
			'>500': [500, 10000000]
		},
		price: {
			'<500k': [0, 500000],
			'500k-1M': [500000, 1000000],
			'1M-2M': [1000000, 2000000],
			'2M-5M': [2000000, 5000000],
			'>5M': [5000000, 9999999999]
		},
		pricePerSqM: {
			'<10000': [0, 10000],
			'10000-20000': [10000, 20000],
			'20000-30000': [20000, 30000],
			'>30000': [30000, 9999999]
		},
		rent: {
			'<50k': [0, 50000],
			'50k-100k': [50000, 100000],
			'100k-200k': [100000, 200000],
			'>200k': [200000, 999999999]
		}
	}

	Object.entries(filters).forEach(([k, v]) => {
		if (v !== undefined && v !== null && v !== 'All') {
			if (k === 'transaction_ids' || k === 'contract_ids') {
				params.append(k, String(v))
			} else if (rangeMap[k] && typeof v === 'string' && rangeMap[k][v]) {
				const [min, max] = rangeMap[k][v]
				if (min !== undefined) params.append(`${k}_min`, String(min))
				if (max !== undefined) params.append(`${k}_max`, String(max))
			} else {
				params.append(k, String(v))
			}
		}
	})
	return params.toString()
}

export const transactions = {
	sales: (filters: TransactionFilters) =>
		client.get<TransactionListResponse>(`/api/v1/transactions/sales?${buildQuery(filters)}`),

	rentals: (filters: TransactionFilters) =>
		client.get<RentalContractListResponse>(`/api/v1/transactions/rentals?${buildQuery(filters)}`),

	exportSales: (filters: TransactionFilters): Promise<Blob> =>
		client.get<Blob>(`/api/v1/transactions/sales/export?${buildQuery(filters)}`, {
			returnBlob: true
		}),

	exportRentals: (filters: TransactionFilters): Promise<Blob> =>
		client.get<Blob>(`/api/v1/transactions/rentals/export?${buildQuery(filters)}`, {
			returnBlob: true
		})
}
