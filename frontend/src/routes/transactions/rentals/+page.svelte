<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { RotateCcw } from 'lucide-svelte'
import { type TransactionExportFormat, transactions } from '$lib/api/transactions'
import FilterPanel from '$lib/components/filters/FilterPanel.svelte'
import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte'
import DataPanel from '$lib/components/transactions/DataPanel.svelte'
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

type FilterChip = {
	label: string
	value: string
}

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
		id: 'selectedLocation',
		label: 'Location',
		type: 'searchable',
		options: ['All', ...(options?.locations ?? [])]
	},
	{
		id: 'selectedBuilding',
		label: 'Building',
		type: 'searchable',
		options: ['All', ...(options?.buildings ?? [])]
	},
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
	{ id: 'sizeRange', label: 'Size (sq.m)', type: 'standard', options: SIZE_OPTIONS },
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
}

function addSelectedChip(chips: FilterChip[], label: string, value: string) {
	if (value && value !== 'All') chips.push({ label, value })
}

function buildActiveFilterChips(): FilterChip[] {
	const chips: FilterChip[] = [
		{ label: 'Dataset', value: propertyType.current },
		{ label: 'Period', value: timeframe.current }
	]

	addSelectedChip(chips, 'Location', localFilters.selectedLocation)
	addSelectedChip(chips, 'Building', localFilters.selectedBuilding)
	addSelectedChip(chips, 'Property type', localFilters.selectedPropertyType)
	if (!isCommercial) addSelectedChip(chips, 'Bedrooms', localFilters.selectedBedrooms)
	addSelectedChip(chips, 'Contract type', localFilters.selectedContractType)
	addSelectedChip(chips, 'Size', localFilters.sizeRange)
	addSelectedChip(chips, 'Annual rent', localFilters.rentRange)

	return chips
}

let activeFilterChips = $derived(buildActiveFilterChips())

// Track filter changes to reset page
let filterKey = $derived(JSON.stringify(localFilters))

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

// Reset page and filters on global filter changes
$effect(() => {
	const _ = [propertyType.current, timeframe.current]
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

<div class="ui-surface relative z-20 p-4 sm:p-5">
	<div class="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
		<div>
			<p class="text-xs font-semibold uppercase tracking-[0.18em] text-fg-4">
				Market controls
			</p>
			<p class="mt-1 text-sm text-fg-3">
				DXBI rental contracts, one row per leased unit, dated by lease start.
			</p>
		</div>
		<button
			type="button"
			onclick={resetFilters}
			data-variant="secondary"
			class="ui-button h-9 w-fit shrink-0 gap-2 px-3 text-xs font-medium sm:h-10 sm:text-sm"
		>
			<RotateCcw size={15} strokeWidth={1.8} />
			Reset filters
		</button>
	</div>
	<div class="hidden lg:block">
		<FilterPanel
			{filterDefinitions}
			bind:filters={localFilters}
			onReset={resetFilters}
			embedded={true}
			showHeader={false}
			idPrefix="rentals-filters-desktop"
		/>
	</div>
	<details class="ui-panel overflow-hidden lg:hidden">
		<summary class="cursor-pointer px-3 py-2.5 text-sm font-semibold text-fg-1">
			Local filters
		</summary>
		<div class="border-t border-border bg-card p-3">
			<FilterPanel
				{filterDefinitions}
				bind:filters={localFilters}
				onReset={resetFilters}
				embedded={true}
				showHeader={false}
				idPrefix="rentals-filters-mobile"
			/>
		</div>
	</details>
</div>

<div
	class="mb-4 flex flex-col gap-3 rounded-md border border-border bg-card px-4 py-3 lg:flex-row lg:items-center lg:justify-between"
>
	<div class="min-w-0">
		<p class="text-xs font-semibold uppercase tracking-[0.18em] text-fg-4">Active filters</p>
		<div class="mt-2 flex flex-wrap gap-2">
			{#each activeFilterChips as chip (chip.label)}
				<span class="rounded-sm border border-border bg-elevated px-2 py-1 text-xs text-fg-2">
					<span class="font-medium text-fg-4">{chip.label}</span>
					<span class="ml-1 font-semibold text-fg-1">{chip.value}</span>
				</span>
			{/each}
		</div>
	</div>
	<div class="shrink-0 text-sm font-medium text-fg-2">
		{formatCount(totalRecords)} matching contracts
	</div>
</div>

<DataPanel
	title="Rental contracts"
	description={selectedContractIds.size > 0
		? `Exporting ${selectedContractIds.size} selected rows as Excel or CSV.`
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
	loading={rentalsQuery.isPending && displayData.length === 0}
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
