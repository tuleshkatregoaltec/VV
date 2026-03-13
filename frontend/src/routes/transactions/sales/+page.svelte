<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { ProjectSearchItem } from '$lib/api/analytics'
import { type TransactionResponseOutput, transactions } from '$lib/api/transactions'
import ProjectSelector from '$lib/components/analytics/ProjectSelector.svelte'
import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte'
import FilterPanel from '$lib/components/filters/FilterPanel.svelte'
import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte'
import DataPanel from '$lib/components/transactions/DataPanel.svelte'
import TransactionDetailsModal from '$lib/components/transactions/TransactionDetailsModal.svelte'
import Pagination from '$lib/components/ui/Pagination.svelte'
import {
	COMMERCIAL_COLUMNS,
	PROPERTY_USAGE,
	RESIDENTIAL_COLUMNS
} from '$lib/constants/transactions'
import { analyticsQueries } from '$lib/queries/analytics'
import { transactionQueries } from '$lib/queries/transactions'
import type { FilterDefinition } from '$lib/types/filters'
import {
	buildSalesApiFilters,
	buildSalesFilterParams,
	withSelectedIds
} from '$lib/utils/transactionPages'

// Area in sq.m (database stores in sqm)
const AREA_OPTIONS = ['All', '<50', '50-100', '100-200', '200-500', '>500']
const PRICE_OPTIONS = ['All', '<500k', '500k-1M', '1M-2M', '2M-5M', '>5M']
// Price per sq.m (database stores price/sqm, typical range 15000-35000 AED/sqm)
const PRICE_SQM_OPTIONS = ['All', '<10000', '10000-20000', '20000-30000', '>30000']

interface TransformedTransaction {
	transaction_id: string
	date: string
	area_name: string
	project: string
	building: string
	propertyType: string
	propertySubType: string
	bedrooms: string
	area: number
	price: number
	pricePerSqM: number
	registration: string
	trans_group: string
	procedure_name: string
	landmark: string
	metro: string
	mall: string
}

// Dropdown context is provided by transactions/+layout.svelte

let currentPage = $state(1)
let selectedTransactionIds = $state(new Set<string>())
let selectedTransaction = $state<TransformedTransaction | null>(null)

// Project selection (outside FilterPanel — uses canonical groupings)
let selectedProject = $state<ProjectSearchItem | null>(null)
let selectedSubProject = $state<string | null>(null)

let localFilters = $state({
	selectedBuilding: 'All',
	selectedPropertyType: 'All',
	selectedBedroomsOrSubType: 'All',
	selectedRegistration: 'All',
	areaRange: 'All',
	priceRange: 'All',
	pricePerSqMRange: 'All'
})

// Sub-projects query — enabled when a master or virtual_master is selected
const subProjectsQuery = createQuery(() =>
	analyticsQueries.subProjects(selectedProject?.name ?? null, selectedProject?.filter_type ?? null)
)

const subProjectOptions = $derived(subProjectsQuery.data?.sub_projects.map((p) => p.name) ?? [])

function buildApiFilters() {
	return buildSalesApiFilters({
		propertyUsage: propertyType.current,
		timeframe: timeframe.current,
		currentPage,
		selectedProject,
		selectedSubProject,
		localFilters
	})
}

const salesApiFilters = $derived(buildApiFilters())

const salesFilterParams = $derived.by(() => {
	return buildSalesFilterParams(
		propertyType.current,
		selectedProject,
		selectedSubProject,
		localFilters.selectedPropertyType
	)
})

// Main transactions query
const transactionsQuery = createQuery(() => transactionQueries.sales(salesApiFilters))

const filterOptionsQuery = createQuery(() =>
	transactionQueries.salesFilterOptions(salesFilterParams)
)

let columns = $derived(
	propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? RESIDENTIAL_COLUMNS : COMMERCIAL_COLUMNS
)

const opts = $derived(filterOptionsQuery.data)

let filterDefinitions = $derived<FilterDefinition[]>([
	{
		id: 'selectedBuilding',
		label: 'Building',
		type: 'searchable',
		options: ['All', ...(opts?.buildings ?? [])]
	},
	{
		id: 'selectedPropertyType',
		label: 'Property Type',
		type: 'standard',
		options: ['All', ...(opts?.property_types ?? [])]
	},
	{
		id: 'selectedBedroomsOrSubType',
		label: propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? 'Bedrooms' : 'Sub Type',
		type: 'standard',
		options: [
			'All',
			...(propertyType.current === PROPERTY_USAGE.RESIDENTIAL
				? (opts?.rooms ?? [])
				: (opts?.property_sub_types ?? []))
		]
	},
	{
		id: 'selectedRegistration',
		label: 'Registration',
		type: 'standard',
		options: ['All', ...(opts?.registration_types ?? [])]
	},
	{
		id: 'areaRange',
		label: 'Area (sq.m)',
		type: 'standard',
		options: AREA_OPTIONS
	},
	{
		id: 'priceRange',
		label: 'Price (AED)',
		type: 'standard',
		options: PRICE_OPTIONS
	},
	{
		id: 'pricePerSqMRange',
		label: 'Price/sq.m (AED)',
		type: 'standard',
		options: PRICE_SQM_OPTIONS
	}
])

function transformTransaction(t: TransactionResponseOutput): TransformedTransaction {
	return {
		transaction_id: t.transaction_id,
		date: t.instance_date ?? '-',
		area_name: t.area_name_en ?? '-',
		project: t.project_name_en ?? '-',
		building: t.building_name_en ?? '-',
		propertyType: t.property_type_en ?? '-',
		propertySubType: t.property_sub_type_en ?? '-',
		bedrooms: t.rooms_en ?? '-',
		area: t.procedure_area ?? 0,
		price: t.actual_worth ?? 0,
		pricePerSqM: t.meter_sale_price ?? 0,
		registration: t.reg_type_en ?? '-',
		trans_group: t.trans_group_en ?? '-',
		procedure_name: t.procedure_name_en ?? '-',
		landmark: t.nearest_landmark_en ?? '-',
		metro: t.nearest_metro_en ?? '-',
		mall: t.nearest_mall_en ?? '-'
	}
}

function getRowId(row: TransformedTransaction): string {
	return row.transaction_id
}

let displayData = $derived(transactionsQuery.data?.transactions.map(transformTransaction) ?? [])

let totalRecords = $derived(transactionsQuery.data?.total ?? 0)
let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE))

function resetFilters() {
	selectedProject = null
	selectedSubProject = null
	localFilters = {
		selectedBuilding: 'All',
		selectedPropertyType: 'All',
		selectedBedroomsOrSubType: 'All',
		selectedRegistration: 'All',
		areaRange: 'All',
		priceRange: 'All',
		pricePerSqMRange: 'All'
	}
	currentPage = 1
}

function handleRowClick(row: TransformedTransaction) {
	selectedTransaction = row
}

// Track filter changes to reset page
let filterKey = $derived(
	JSON.stringify({
		project: selectedProject?.name,
		filterType: selectedProject?.filter_type,
		subProject: selectedSubProject,
		building: localFilters.selectedBuilding,
		propertyType: localFilters.selectedPropertyType,
		bedroomsOrSubType: localFilters.selectedBedroomsOrSubType,
		registration: localFilters.selectedRegistration,
		areaRange: localFilters.areaRange,
		priceRange: localFilters.priceRange,
		pricePerSqMRange: localFilters.pricePerSqMRange
	})
)

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

// Reset page and filters on global filter changes
$effect(() => {
	const _ = [propertyType.current, timeframe.current]
	currentPage = 1
	resetFilters()
	selectedTransactionIds = new Set() // Clear selection on global filter change
})

let isExporting = $state(false)

async function handleExport() {
	isExporting = true
	try {
		const filters = withSelectedIds(buildApiFilters(), 'transaction_ids', selectedTransactionIds)
		const blob = await transactions.exportSales(filters)

		const url = window.URL.createObjectURL(blob)
		const a = document.createElement('a')
		a.href = url
		a.download = `sales_export_${Date.now()}.xlsx`
		document.body.appendChild(a)
		a.click()
		window.URL.revokeObjectURL(url)
		document.body.removeChild(a)
	} catch (error) {
		console.error('Export failed:', error)
		alert(`Failed to export data: ${error instanceof Error ? error.message : 'Unknown error'}`)
	} finally {
		isExporting = false
	}
}
</script>

{#if transactionsQuery.isError}
	<div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6 shadow-sm">
		<p class="text-red-800 font-semibold">Error loading data</p>
		<p class="text-red-600 mt-2">{transactionsQuery.error?.message ?? 'Unknown error'}</p>
		<button
			onclick={() => transactionsQuery.refetch()}
			class="mt-4 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors shadow-sm"
		>
			Retry
		</button>
	</div>
{/if}

<div
	class="relative z-20 bg-white/80 backdrop-blur-sm rounded-xl shadow-sm border border-slate-200 px-6 pt-6 pb-4 mb-2"
>
	<div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
			<div class="flex flex-col gap-2">
				<label for="sales-project" class="block text-sm text-slate-900">Project</label>
				<ProjectSelector
					id="sales-project"
					ariaLabel="Project"
					bind:value={selectedProject}
					placeholder="Search project..."
					onSelect={() => {
					selectedSubProject = null;
					currentPage = 1;
				}}
			/>
		</div>
			{#if selectedProject && selectedProject.filter_type !== 'project'}
				<div class="flex flex-col gap-2">
					<label for="sales-sub-project-button" class="block text-sm text-slate-900">
						Sub-project
					</label>
					<SearchableDropdown
						id="sales-sub-project"
						ariaLabel="Sub-project"
					options={['All', ...subProjectOptions]}
					value={selectedSubProject ?? 'All'}
					onchange={(v) => {
						selectedSubProject = v === 'All' ? null : v;
						currentPage = 1;
					}}
				/>
			</div>
		{/if}
	</div>
</div>

<FilterPanel
	{filterDefinitions}
	bind:filters={localFilters}
	onReset={resetFilters}
	onExport={handleExport}
	selectedCount={selectedTransactionIds.size}
	onClearSelection={() => (selectedTransactionIds = new Set())}
/>

<DataPanel
	{columns}
	data={displayData}
	onrowclick={handleRowClick}
	loading={transactionsQuery.isPending || transactionsQuery.isFetching}
	selectable={true}
	bind:selectedIds={selectedTransactionIds}
	{getRowId}
/>

<div class="mt-6">
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
