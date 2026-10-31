<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { type TransactionExportFormat, transactions } from '$lib/api/transactions'
import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte'
import DataPanel from '$lib/components/transactions/DataPanel.svelte'
import TransactionFilters from '$lib/components/transactions/TransactionFilters.svelte'
import Pagination from '$lib/components/ui/Pagination.svelte'
import {
	DEFAULT_ITEMS_PER_PAGE,
	formatCount,
	PROPERTY_USAGE,
	RENTAL_COLUMNS
} from '$lib/constants/transactions'
import { transactionQueries } from '$lib/queries/transactions'
import type { FilterDefinition } from '$lib/types/filters'
import {
	buildRentalsApiFilters,
	buildRentalsFilterParams,
	DEFAULT_RENTALS_LOCAL_FILTERS,
	RENT_OPTIONS,
	type RentalRow,
	type RentalsLocalFilters,
	SIZE_OPTIONS,
	toRentalRow,
	withSelectedIds
} from '$lib/utils/transactionPages'

// DXBI leases only (dxbi_rental_events): no DLD row or value is shown on this page.
let currentPage = $state(1)
let selectedContractIds = $state(new Set<string>())

let localFilters = $state<RentalsLocalFilters>({ ...DEFAULT_RENTALS_LOCAL_FILTERS })

const isCommercial = $derived(propertyType.current === PROPERTY_USAGE.COMMERCIAL)

function buildApiFilters() {
	return buildRentalsApiFilters({
		propertyUsage: propertyType.current,
		timeframe: timeframe.current,
		currentPage,
		localFilters
	})
}

const rentalsApiFilters = $derived(buildApiFilters())

// Main rentals query
const rentalsQuery = createQuery(() => transactionQueries.rentals(rentalsApiFilters))

// One shared facet payload: every option list in a single scan, narrowed by the filters applied.
const facetOptionsQuery = createQuery(() =>
	transactionQueries.rentalFilterOptions(
		buildRentalsFilterParams({
			propertyUsage: propertyType.current,
			timeframe: timeframe.current,
			localFilters
		})
	)
)

const options = $derived(facetOptionsQuery.data)

// Bedrooms describe homes: the Commercial view has neither the filter nor the column.
const columns = $derived(
	isCommercial ? RENTAL_COLUMNS.filter((column) => column.id !== 'bedrooms') : RENTAL_COLUMNS
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
		id: 'selectedContractType',
		label: 'Contract Type',
		type: 'standard',
		options: ['All', ...(options?.contract_types ?? [])]
	},
	{ id: 'sizeRange', label: 'Size (sq ft)', type: 'standard', options: SIZE_OPTIONS },
	{ id: 'rentRange', label: 'Annual Rent (AED)', type: 'standard', options: RENT_OPTIONS }
])

function getRowId(row: RentalRow): string {
	return row.contract_id
}

let displayData = $derived(rentalsQuery.data?.contracts.map(toRentalRow) ?? [])

let totalRecords = $derived(rentalsQuery.data?.total ?? 0)
let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE))

function resetFilters() {
	localFilters = { ...DEFAULT_RENTALS_LOCAL_FILTERS }
	currentPage = 1
	selectedContractIds = new Set()
}

// Track filter changes to reset page
let filterKey = $derived(JSON.stringify([localFilters, timeframe.current, propertyType.current]))

let lastFilterKey = ''

// Reset to page 1 when filters change
$effect(() => {
	if (filterKey !== lastFilterKey) {
		if (lastFilterKey !== '') {
			currentPage = 1
			selectedContractIds = new Set() // Clear selection on filter change
		}
		lastFilterKey = filterKey
	}
})

// A usage change starts a new search; a period change preserves the chosen property filters.
$effect(() => {
	const _ = propertyType.current
	currentPage = 1
	resetFilters()
	selectedContractIds = new Set() // Clear selection on global filter change
})

let exportingFormat = $state<TransactionExportFormat | null>(null)

async function handleExport(format: TransactionExportFormat) {
	exportingFormat = format
	try {
		const filters = withSelectedIds(buildApiFilters(), 'contract_ids', selectedContractIds)
		const blob = await transactions.exportRentals(filters, format)

		const url = window.URL.createObjectURL(blob)
		const a = document.createElement('a')
		a.href = url
		a.download = `rentals_export_${Date.now()}.${format}`
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

{#if rentalsQuery.isError}
	<div class="mb-6 rounded-lg border border-[rgba(163,36,36,0.2)] bg-error-bg p-6 text-center">
		<p class="font-semibold text-error">Error loading data</p>
		<p class="mt-2 text-error">{rentalsQuery.error?.message ?? 'Unknown error'}</p>
		<button
			onclick={() => rentalsQuery.refetch()}
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
    kind="rentals"
    definitions={filterDefinitions}
    bind:filters={localFilters}
    loading={facetOptionsQuery.isFetching}
    unavailable={facetOptionsQuery.isError || !facetOptionsQuery.data}
    onReset={() => { resetFilters(); timeframe.current = 'Last Month' }}
/>

<div class="flex flex-wrap items-center justify-between gap-2 px-1 text-xs text-fg-3">
    <span>Rental records · Dated by lease start</span>
    <span aria-live="polite">{#if rentalsQuery.isPlaceholderData}Updating matching contracts…{:else}{formatCount(totalRecords)} matching contracts{/if}</span>
</div>

<DataPanel
	title="Rental contracts"
	description={selectedContractIds.size > 0
		? `Exporting ${selectedContractIds.size} selected rows as Excel or CSV.`
		: 'Export the filtered rows as Excel or CSV, up to 50,000 rows.'}
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
	loading={rentalsQuery.isPending || rentalsQuery.isPlaceholderData}
	selectable={true}
	bind:selectedIds={selectedContractIds}
	{getRowId}
/>

<div class="mt-2 px-1">
	<Pagination
		bind:currentPage
		{totalPages}
		totalItems={totalRecords}
		itemsPerPage={DEFAULT_ITEMS_PER_PAGE}
		itemLabel="contracts"
	/>
</div>
