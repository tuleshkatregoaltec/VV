<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { type TransactionExportFormat, transactions } from '$lib/api/transactions'
import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte'
import DataPanel from '$lib/components/transactions/DataPanel.svelte'
import TransactionDetailsModal from '$lib/components/transactions/TransactionDetailsModal.svelte'
import TransactionFilters from '$lib/components/transactions/TransactionFilters.svelte'
import Pagination from '$lib/components/ui/Pagination.svelte'
import {
	DEFAULT_ITEMS_PER_PAGE,
	formatCount,
	PROPERTY_USAGE,
	SALES_COLUMNS
} from '$lib/constants/transactions'
import { transactionQueries } from '$lib/queries/transactions'
import type { FilterDefinition } from '$lib/types/filters'
import {
	buildSalesApiFilters,
	buildSalesFilterParams,
	DEFAULT_SALES_LOCAL_FILTERS,
	SALES_PRICE_OPTIONS,
	SALES_PRICE_SQFT_OPTIONS,
	type SaleRow,
	type SalesLocalFilters,
	SIZE_OPTIONS,
	toSaleRow,
	withSelectedIds
} from '$lib/utils/transactionPages'

// DXBI sales only (dxbi_sales_unit_events): no DLD row or value is shown on this page.
let currentPage = $state(1)
let selectedTransactionIds = $state(new Set<string>())
let selectedTransaction = $state<SaleRow | null>(null)

let localFilters = $state<SalesLocalFilters>({ ...DEFAULT_SALES_LOCAL_FILTERS })

const isCommercial = $derived(propertyType.current === PROPERTY_USAGE.COMMERCIAL)

function buildApiFilters() {
	return buildSalesApiFilters({
		propertyUsage: propertyType.current,
		timeframe: timeframe.current,
		currentPage,
		localFilters
	})
}

const salesApiFilters = $derived(buildApiFilters())

// Main transactions query
const transactionsQuery = createQuery(() => transactionQueries.sales(salesApiFilters))

// One shared facet payload: every option list in a single scan, narrowed by the filters applied.
const facetOptionsQuery = createQuery(() =>
	transactionQueries.salesFilterOptions(
		buildSalesFilterParams({
			propertyUsage: propertyType.current,
			timeframe: timeframe.current,
			localFilters
		})
	)
)

const options = $derived(facetOptionsQuery.data)

// Bedrooms describe homes: the Commercial view has neither the filter nor the column.
const columns = $derived(
	isCommercial ? SALES_COLUMNS.filter((column) => column.id !== 'bedrooms') : SALES_COLUMNS
)

let filterDefinitions = $derived<FilterDefinition[]>([
	{
		id: 'selectedPropertyType',
		label: 'Property Type',
		type: 'standard',
		options: ['All', ...(options?.property_types ?? [])]
	},
	...(isCommercial
		? []
		: [
				{
					id: 'selectedBedrooms',
					label: 'Bedrooms',
					type: 'standard' as const,
					options: ['All', ...(options?.bedrooms ?? [])]
				}
			]),
	{
		id: 'selectedStatus',
		label: 'Status',
		type: 'standard',
		options: ['All', ...(options?.statuses ?? [])]
	},
	{ id: 'sizeRange', label: 'Size (sq ft)', type: 'standard', options: SIZE_OPTIONS },
	{ id: 'priceRange', label: 'Price Range (AED)', type: 'standard', options: SALES_PRICE_OPTIONS },
	{
		id: 'pricePerSqFtRange',
		label: 'Price/sq ft (AED)',
		type: 'standard',
		options: SALES_PRICE_SQFT_OPTIONS
	}
])

function getRowId(row: SaleRow): string {
	return row.transaction_id
}

let displayData = $derived(transactionsQuery.data?.transactions.map(toSaleRow) ?? [])

let totalRecords = $derived(transactionsQuery.data?.total ?? 0)
let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE))

function resetFilters() {
	localFilters = { ...DEFAULT_SALES_LOCAL_FILTERS }
	currentPage = 1
	selectedTransactionIds = new Set()
}

function handleRowClick(row: SaleRow) {
	selectedTransaction = row
}

// Track filter changes to reset page
let filterKey = $derived(JSON.stringify([localFilters, timeframe.current, propertyType.current]))

let lastFilterKey = ''

// Reset to page 1 when filters change
$effect(() => {
	if (filterKey !== lastFilterKey) {
		if (lastFilterKey !== '') {
			currentPage = 1
			selectedTransactionIds = new Set() // Clear selection on filter change
		}
		lastFilterKey = filterKey
	}
})

// A usage change starts a new search; a period change preserves the chosen property filters.
$effect(() => {
	const _ = propertyType.current
	currentPage = 1
	resetFilters()
	selectedTransactionIds = new Set() // Clear selection on global filter change
})

let exportingFormat = $state<TransactionExportFormat | null>(null)

async function handleExport(format: TransactionExportFormat) {
	exportingFormat = format
	try {
		const filters = withSelectedIds(buildApiFilters(), 'transaction_ids', selectedTransactionIds)
		const blob = await transactions.exportSales(filters, format)

		const url = window.URL.createObjectURL(blob)
		const a = document.createElement('a')
		a.href = url
		a.download = `sales_export_${Date.now()}.${format}`
		document.body.appendChild(a)
		a.click()
		window.URL.revokeObjectURL(url)
		document.body.removeChild(a)
	} catch (error) {
		console.error('Export failed:', error)
		alert(`Failed to export data: ${error instanceof Error ? error.message : 'Unknown error'}`)
	} finally {
		exportingFormat = null
	}
}
</script>

{#if transactionsQuery.isError}
	<div class="mb-6 rounded-lg border border-[rgba(163,36,36,0.2)] bg-error-bg p-6 text-center">
		<p class="font-semibold text-error">Error loading data</p>
		<p class="mt-2 text-error">{transactionsQuery.error?.message ?? 'Unknown error'}</p>
		<button
			onclick={() => transactionsQuery.refetch()}
			class="mt-4 rounded-md border border-navy bg-navy px-4 py-2 text-sm font-medium text-on-navy transition-colors hover:bg-primary-hover"
		>
			Retry
		</button>
	</div>
{/if}

{#if facetOptionsQuery.isError}
	<div role="alert" class="mb-4 rounded-lg border border-error bg-error-bg p-4 text-sm text-error">
		<p>Error loading filters. Filter options are unavailable. Clear selections or retry.</p>
		<button type="button" class="ui-button mt-2" disabled={facetOptionsQuery.isFetching} onclick={() => facetOptionsQuery.refetch()}>Retry filters</button>
	</div>
{/if}

<TransactionFilters
    suggestions={[...new Set([...(options?.buildings ?? []), ...(options?.projects ?? []), ...(options?.locations ?? [])])]}
    kind="sales"
    definitions={filterDefinitions}
    bind:filters={localFilters}
    loading={facetOptionsQuery.isFetching}
    unavailable={facetOptionsQuery.isError || !facetOptionsQuery.data}
    onReset={() => { resetFilters(); timeframe.current = 'Last Month' }}
/>

<div class="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-fg-3">
    <span>DXBI sales records</span>
    <span aria-live="polite">{#if transactionsQuery.isPlaceholderData}Updating matching transactions…{:else}{formatCount(totalRecords)} matching transactions{/if}</span>
</div>

<DataPanel
	title="Sales records"
	description={selectedTransactionIds.size > 0
		? `Exporting ${selectedTransactionIds.size} selected rows as Excel or CSV.`
		: 'Export the filtered DXBI rows as Excel or CSV, up to 50,000 rows.'}
	exportActions={[
		{
			label: 'Excel',
			onClick: () => handleExport('xlsx'),
			disabled: exportingFormat !== null
		},
		{
			label: 'CSV',
			onClick: () => handleExport('csv'),
			disabled: exportingFormat !== null,
			variant: 'secondary'
		}
	]}
	{columns}
	data={displayData}
	onrowclick={handleRowClick}
	loading={transactionsQuery.isPending || transactionsQuery.isPlaceholderData}
	selectable={true}
	bind:selectedIds={selectedTransactionIds}
	{getRowId}
/>

<div class="mt-2 px-1">
	<Pagination
		bind:currentPage
		{totalPages}
		totalItems={totalRecords}
		itemsPerPage={DEFAULT_ITEMS_PER_PAGE}
		itemLabel="transactions"
	/>
</div>

<TransactionDetailsModal
	transaction={selectedTransaction}
	onClose={() => (selectedTransaction = null)}
/>
