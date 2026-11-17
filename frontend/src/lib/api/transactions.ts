import { client } from './client'
import type {
	RentalContractListResponse,
	RentalContractResponse,
	TransactionListResponse,
	TransactionResponse
} from './generated/hey-api/types.gen'

export type RentalContractResponseOutput = RentalContractResponse
export type TransactionResponseOutput = TransactionResponse
export type TransactionExportFormat = 'xlsx' | 'csv'
export type {
	RentalContractListResponse,
	TransactionListResponse,
	RentalContractResponse,
	TransactionResponse
}

// Filters of the DXBI Transactions pages. Sizes in sq ft; range bounds are half-open (min
// inclusive, max exclusive).
interface BaseTransactionFilters {
	property_usage?: string
	property_type?: string
	bedrooms?: string
	location_search?: string
	location?: string
	building?: string
	project?: string
	timeframe_days?: number
	size_min?: number
	size_max?: number
	limit?: number
	offset?: number
}

export interface SalesTransactionFilters extends BaseTransactionFilters {
	status?: string
	price_min?: number
	price_max?: number
	price_per_sqft_min?: number
	price_per_sqft_max?: number
	transaction_ids?: string
}

export interface RentalTransactionFilters extends BaseTransactionFilters {
	contract_type?: string
	rent_min?: number
	rent_max?: number
	contract_ids?: string
}

export type SalesFacetFilters = Omit<
	SalesTransactionFilters,
	'limit' | 'offset' | 'transaction_ids'
>
export type RentalFacetFilters = Omit<RentalTransactionFilters, 'limit' | 'offset' | 'contract_ids'>

/** An export file and how it relates to the rows the filters matched. */
export interface TransactionExportFile {
	blob: Blob
	rows: number
	matchingRows: number
	truncated: boolean
}

async function exportFile(response: Response): Promise<TransactionExportFile> {
	const rows = Number(response.headers.get('X-Export-Rows') ?? Number.NaN)
	const matchingRows = Number(response.headers.get('X-Export-Matching-Rows') ?? Number.NaN)
	return {
		blob: await response.blob(),
		rows,
		matchingRows,
		truncated: response.headers.get('X-Export-Truncated') === 'true'
	}
}

/** What to tell the user when an export holds only the newest rows of a larger selection. */
export function exportTruncationNotice(
	file: TransactionExportFile,
	noun: 'sales' | 'leases'
): string | null {
	if (!file.truncated) return null
	return `This file holds the newest ${file.rows.toLocaleString('en-US')} of ${file.matchingRows.toLocaleString('en-US')} matching ${noun}. Narrow the filters to export the rest.`
}

function withFilters(
	endpoint: string,
	filters: BaseTransactionFilters & { format?: TransactionExportFormat }
) {
	return client.withQuery(
		endpoint,
		filters as Record<string, string | number | boolean | null | undefined>
	)
}

export const transactions = {
	sales: (filters: SalesTransactionFilters) =>
		client.get<TransactionListResponse>(withFilters('/api/v1/transactions/sales', filters)),

	rentals: (filters: RentalTransactionFilters) =>
		client.get<RentalContractListResponse>(withFilters('/api/v1/transactions/rentals', filters)),

	exportSales: async (
		filters: SalesTransactionFilters,
		format: TransactionExportFormat = 'xlsx'
	): Promise<TransactionExportFile> =>
		exportFile(
			await client.get<Response>(
				withFilters('/api/v1/transactions/sales/export', { ...filters, format }),
				{ returnResponse: true }
			)
		),

	exportRentals: async (
		filters: RentalTransactionFilters,
		format: TransactionExportFormat = 'xlsx'
	): Promise<TransactionExportFile> =>
		exportFile(
			await client.get<Response>(
				withFilters('/api/v1/transactions/rentals/export', { ...filters, format }),
				{ returnResponse: true }
			)
		)
}
