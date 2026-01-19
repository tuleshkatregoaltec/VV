import { api } from './client';
import { env } from '$env/dynamic/public';

export interface Transaction {
	transaction_id: string;
	project_name_en: string | null;
	building_name_en: string | null;
	property_type_en: string | null;
	property_sub_type_en: string | null;
	rooms_en: string | null;
	procedure_area: number | null;
	actual_worth: number | null;
	meter_sale_price: number | null;
	reg_type_en: string | null;
	instance_date: string | null;
	area_name_en: string | null;
}

export interface TransactionListResponse {
	transactions: Transaction[];
	total: number;
	limit: number;
	offset: number;
}

export interface RentalContract {
	contract_id: string;
	project_name_en: string | null;
	ejari_property_type_en: string | null;
	ejari_property_sub_type_en: string | null;
	tenant_type_en: string | null;
	actual_area: number | null;
	annual_amount: number | null;
	contract_reg_type_en: string | null;
	contract_start_date: string | null;
	contract_end_date: string | null;
	area_name_en: string | null;
}

export interface RentalContractListResponse {
	contracts: RentalContract[];
	total: number;
	limit: number;
	offset: number;
}

export interface TransactionFilters {
	trans_group?: string;
	property_usage?: string;
	master_project?: string;
	timeframe_days?: number;
	project?: string;
	building?: string;
	property_type?: string;
	rooms?: string;
	property_sub_type?: string;
	registration_type?: string;
	area?: string;
	area_min?: number;
	area_max?: number;
	price?: string;
	price_min?: number;
	price_max?: number;
	pricePerSqM?: string;
	pricePerSqFt?: string;
	price_sqft_min?: number;
	price_sqft_max?: number;
	annualRent?: string;
	transaction_ids?: string;
	contract_ids?: string;
	limit?: number;
	offset?: number;
}

function buildQuery(filters: TransactionFilters): string {
	const params = new URLSearchParams();
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
		pricePerSqFt: {
			'<10000': [0, 10000],
			'10000-20000': [10000, 20000],
			'20000-30000': [20000, 30000],
			'>30000': [30000, 9999999]
		},
		annualRent: {
			'<50k': [0, 50000],
			'50k-100k': [50000, 100000],
			'100k-200k': [100000, 200000],
			'>200k': [200000, 999999999]
		}
	};

	Object.entries(filters).forEach(([k, v]) => {
		if (v !== undefined && v !== null && v !== 'All') {
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
	sales: (filters: TransactionFilters) =>
		api<TransactionListResponse>(`/api/v1/transactions/sales?${buildQuery(filters)}`),

	rentals: (filters: TransactionFilters) =>
		api<RentalContractListResponse>(`/api/v1/transactions/rentals?${buildQuery(filters)}`),

	exportSales: (filters: TransactionFilters): Promise<Blob> =>
		api<Blob>(`/api/v1/transactions/sales/export?${buildQuery(filters)}`, { returnBlob: true }),

	exportRentals: (filters: TransactionFilters): Promise<Blob> =>
		api<Blob>(`/api/v1/transactions/rentals/export?${buildQuery(filters)}`, { returnBlob: true })
};
