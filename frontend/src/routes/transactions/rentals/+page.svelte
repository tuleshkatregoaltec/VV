<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import DataPanel from '$lib/components/transactions/DataPanel.svelte';
	import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
	import Pagination from '$lib/components/ui/Pagination.svelte';
	import ProjectSelector from '$lib/components/analytics/ProjectSelector.svelte';
	import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte';
	import { transactions as api } from '$lib/api/transactions';
	import { filters } from '$lib/api/filters';
	import { analytics, type ProjectSearchItem } from '$lib/api/analytics';
	import type { RentalContract } from '$lib/api/transactions';
	import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte';
	import { TIMEFRAME_MAPPING, DEFAULT_ITEMS_PER_PAGE } from '$lib/constants/transactions';
	import type { FilterDefinition } from '$lib/types/filters';

	// Area in sq.m (database stores in sqm)
	const AREA_OPTIONS = ['All', '<50', '50-100', '100-200', '200-500', '>500'];
	const ANNUAL_RENT_OPTIONS = ['All', '<50k', '50k-100k', '100k-200k', '>200k'];

	interface TransformedRental {
		contract_id: string;
		startDate: string;
		endDate: string;
		area_name: string;
		project: string;
		propertyType: string;
		propertySubType: string;
		tenantType: string;
		area: number;
		annualRent: number;
		registration: string;
		contractAmount: number | null;
		numProperties: number | null;
		freehold: string;
		landmark: string;
		metro: string;
		mall: string;
	}

	// Column configuration for rentals
	const RENTAL_COLUMNS = [
		{ id: 'startDate', label: 'Start Date', align: 'left' as const, defaultVisible: true },
		{ id: 'endDate', label: 'End Date', align: 'left' as const, defaultVisible: true },
		{ id: 'area_name', label: 'Area', align: 'left' as const, defaultVisible: false },
		{ id: 'project', label: 'Project', align: 'left' as const, defaultVisible: true },
		{ id: 'propertyType', label: 'Property Type', align: 'left' as const, defaultVisible: true },
		{ id: 'propertySubType', label: 'Sub Type', align: 'left' as const, defaultVisible: true },
		{
			id: 'tenantType',
			label: 'Tenant Type',
			align: 'left' as const,
			badge: true,
			defaultVisible: true
		},
		{
			id: 'area',
			label: 'Area (sq.m)',
			align: 'right' as const,
			format: (val: number) => val.toLocaleString(),
			defaultVisible: true
		},
		{
			id: 'annualRent',
			label: 'Annual Rent (AED)',
			align: 'right' as const,
			highlighted: true,
			format: (val: number) => val.toLocaleString(),
			defaultVisible: true
		},
		{ id: 'registration', label: 'Reg Type', align: 'left' as const, defaultVisible: false },
		{
			id: 'contractAmount',
			label: 'Contract Amount (AED)',
			align: 'right' as const,
			format: (val: number) => val?.toLocaleString() ?? '-',
			defaultVisible: false
		},
		{ id: 'numProperties', label: '# Properties', align: 'right' as const, defaultVisible: false },
		{ id: 'freehold', label: 'Freehold', align: 'left' as const, defaultVisible: false },
		{ id: 'landmark', label: 'Landmark', align: 'left' as const, defaultVisible: false },
		{ id: 'metro', label: 'Nearest Metro', align: 'left' as const, defaultVisible: false },
		{ id: 'mall', label: 'Nearest Mall', align: 'left' as const, defaultVisible: false }
	];

	// Dropdown context is provided by transactions/+layout.svelte

	// ========================================
	// Local State
	// ========================================
	let currentPage = $state(1);
	let selectedContractIds = $state(new Set<string>());

	// Project selection (outside FilterPanel — uses canonical groupings)
	let selectedProject = $state<ProjectSearchItem | null>(null);
	let selectedSubProject = $state<string | null>(null);

	let localFilters = $state({
		selectedPropertyType: 'All',
		selectedPropertySubType: 'All',
		selectedTenantType: 'All',
		selectedRegistration: 'All',
		areaRange: 'All',
		rentRange: 'All'
	});

	// Sub-projects query — enabled when a master or virtual_master is selected
	const subProjectsQuery = createQuery(() => ({
		queryKey: ['sub-projects', selectedProject?.name, selectedProject?.filter_type],
		queryFn: () => analytics.subProjects(selectedProject!.name, selectedProject!.filter_type),
		enabled: !!selectedProject && selectedProject.filter_type !== 'project',
		staleTime: Infinity
	}));

	const subProjectOptions = $derived(subProjectsQuery.data?.sub_projects.map((p) => p.name) ?? []);

	// ========================================
	// Build API Filters
	// ========================================
	function buildApiFilters() {
		const apiFilters: Record<string, any> = {
			property_usage: propertyType.current,
			timeframe_days: TIMEFRAME_MAPPING[timeframe.current],
			limit: DEFAULT_ITEMS_PER_PAGE,
			offset: (currentPage - 1) * DEFAULT_ITEMS_PER_PAGE
		};

		// Project filter — use sub-project if selected, otherwise canonical grouping
		if (selectedSubProject) {
			apiFilters.project = selectedSubProject;
			apiFilters.filter_type = 'project';
		} else if (selectedProject) {
			apiFilters.project = selectedProject.name;
			apiFilters.filter_type = selectedProject.filter_type;
		}

		if (localFilters.selectedPropertyType !== 'All') {
			apiFilters.property_type = localFilters.selectedPropertyType;
		}
		if (localFilters.selectedPropertySubType !== 'All') {
			apiFilters.property_sub_type = localFilters.selectedPropertySubType;
		}
		if (localFilters.selectedTenantType !== 'All') {
			apiFilters.tenant_type = localFilters.selectedTenantType;
		}
		if (localFilters.selectedRegistration !== 'All') {
			apiFilters.contract_reg_type = localFilters.selectedRegistration;
		}

		// Range filters
		if (localFilters.areaRange !== 'All') {
			apiFilters.area = localFilters.areaRange;
		}
		if (localFilters.rentRange !== 'All') {
			apiFilters.rent = localFilters.rentRange;
		}

		return apiFilters;
	}

	// ========================================
	// TanStack Queries
	// ========================================

	// Derive query key explicitly to ensure proper reactivity tracking
	let rentalsQueryKey = $derived([
		'rental-contracts',
		propertyType.current,
		timeframe.current,
		currentPage,
		selectedProject?.name,
		selectedProject?.filter_type,
		selectedSubProject,
		localFilters.selectedPropertyType,
		localFilters.selectedPropertySubType,
		localFilters.selectedTenantType,
		localFilters.selectedRegistration,
		localFilters.areaRange,
		localFilters.rentRange
	]);

	// Main rentals query
	const rentalsQuery = createQuery(() => ({
		queryKey: rentalsQueryKey,
		queryFn: () => api.rentals(buildApiFilters())
	}));

	// Derive filter options query key explicitly
	let filterOptionsQueryKey = $derived([
		'filterOptions',
		'rentals',
		propertyType.current,
		selectedProject?.name,
		selectedProject?.filter_type,
		selectedSubProject,
		localFilters.selectedPropertyType
	]);

	// Filter options query
	const filterOptionsQuery = createQuery(() => ({
		queryKey: filterOptionsQueryKey,
		queryFn: () => {
			const filterParams: Record<string, any> = {
				property_usage: propertyType.current
			};

			// Narrow by project selection (same logic as main query)
			if (selectedSubProject) {
				filterParams.project = selectedSubProject;
				filterParams.filter_type = 'project';
			} else if (selectedProject) {
				filterParams.project = selectedProject.name;
				filterParams.filter_type = selectedProject.filter_type;
			}

			if (localFilters.selectedPropertyType !== 'All') {
				filterParams.property_type = localFilters.selectedPropertyType;
			}

			return filters.rentals(filterParams);
		},
		staleTime: 5 * 60 * 1000 // 5 minutes
	}));

	// ========================================
	// Derived Values
	// ========================================

	const opts = $derived(filterOptionsQuery.data);

	let filterDefinitions = $derived<FilterDefinition[]>([
		{
			id: 'selectedPropertyType',
			label: 'Property Type',
			type: 'standard',
			options: ['All', ...(opts?.property_types ?? [])]
		},
		{
			id: 'selectedPropertySubType',
			label: 'Sub Type',
			type: 'standard',
			options: ['All', ...(opts?.property_sub_types ?? [])]
		},
		{
			id: 'selectedTenantType',
			label: 'Tenant Type',
			type: 'standard',
			options: ['All', ...(opts?.tenant_types ?? [])]
		},
		{
			id: 'selectedRegistration',
			label: 'Reg Type',
			type: 'standard',
			options: ['All', ...(opts?.contract_reg_types ?? [])]
		},
		{
			id: 'areaRange',
			label: 'Area (sq.m)',
			type: 'standard',
			options: AREA_OPTIONS
		},
		{
			id: 'rentRange',
			label: 'Annual Rent (AED)',
			type: 'standard',
			options: ANNUAL_RENT_OPTIONS
		}
	]);

	function transformRental(r: RentalContract): TransformedRental {
		return {
			contract_id: r.contract_id,
			startDate: r.contract_start_date ?? '-',
			endDate: r.contract_end_date ?? '-',
			area_name: r.area_name_en ?? '-',
			project: r.project_name_en ?? '-',
			propertyType: r.ejari_property_type_en ?? '-',
			propertySubType: r.ejari_property_sub_type_en ?? '-',
			tenantType: r.tenant_type_en ?? '-',
			area: r.actual_area ?? 0,
			annualRent: r.annual_amount ?? 0,
			registration: r.contract_reg_type_en ?? '-',
			contractAmount: r.contract_amount,
			numProperties: r.no_of_prop,
			freehold: r.is_free_hold === null ? '-' : r.is_free_hold ? 'Yes' : 'No',
			landmark: r.nearest_landmark_en ?? '-',
			metro: r.nearest_metro_en ?? '-',
			mall: r.nearest_mall_en ?? '-'
		};
	}

	function getRowId(row: TransformedRental): string {
		return row.contract_id;
	}

	let displayData = $derived(rentalsQuery.data?.contracts.map(transformRental) ?? []);

	let totalRecords = $derived(rentalsQuery.data?.total ?? 0);
	let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE));

	const columns = RENTAL_COLUMNS;

	// ========================================
	// Actions
	// ========================================

	function resetFilters() {
		selectedProject = null;
		selectedSubProject = null;
		localFilters = {
			selectedPropertyType: 'All',
			selectedPropertySubType: 'All',
			selectedTenantType: 'All',
			selectedRegistration: 'All',
			areaRange: 'All',
			rentRange: 'All'
		};
		currentPage = 1;
	}

	function handleRowClick(row: TransformedRental) {
		console.log('Contract clicked:', row);
	}

	// ========================================
	// Effects
	// ========================================

	// Track filter changes to reset page
	let filterKey = $derived(
		JSON.stringify({
			project: selectedProject?.name,
			filterType: selectedProject?.filter_type,
			subProject: selectedSubProject,
			propertyType: localFilters.selectedPropertyType,
			propertySubType: localFilters.selectedPropertySubType,
			tenantType: localFilters.selectedTenantType,
			registration: localFilters.selectedRegistration,
			areaRange: localFilters.areaRange,
			rentRange: localFilters.rentRange
		})
	);

	let lastFilterKey = '';

	// Reset to page 1 when filters change
	$effect(() => {
		if (filterKey !== lastFilterKey) {
			if (lastFilterKey !== '') {
				currentPage = 1;
				selectedContractIds = new Set(); // Clear selection on filter change
			}
			lastFilterKey = filterKey;
		}
	});

	// Reset page and filters on global filter changes
	$effect(() => {
		const _ = [propertyType.current, timeframe.current];
		currentPage = 1;
		resetFilters();
		selectedContractIds = new Set(); // Clear selection on global filter change
	});

	// Export support (same logic as sales page)
	let isExporting = $state(false);

	async function handleExport() {
		isExporting = true;
		try {
			const filters = buildApiFilters();

			// Add selected contract IDs if any are selected
			if (selectedContractIds.size > 0) {
				filters.contract_ids = Array.from(selectedContractIds).join(',');
			}

			const blob = await api.exportRentals(filters);

			const url = window.URL.createObjectURL(blob);
			const a = document.createElement('a');
			a.href = url;
			a.download = `rentals_export_${Date.now()}.xlsx`;
			document.body.appendChild(a);
			a.click();
			window.URL.revokeObjectURL(url);
			document.body.removeChild(a);
		} catch (error) {
			console.error('Export failed:', error);
			alert(`Failed to export data: ${error instanceof Error ? error.message : 'Unknown error'}`);
		} finally {
			isExporting = false;
		}
	}
</script>

{#if rentalsQuery.isError}
	<div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6 shadow-sm">
		<p class="text-red-800 font-semibold">Error loading data</p>
		<p class="text-red-600 mt-2">{rentalsQuery.error?.message ?? 'Unknown error'}</p>
		<button
			onclick={() => rentalsQuery.refetch()}
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
			<label class="block text-sm text-slate-900">Project</label>
			<ProjectSelector
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
				<label class="block text-sm text-slate-900">Sub-project</label>
				<SearchableDropdown
					id="rentals-sub-project"
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
	selectedCount={selectedContractIds.size}
	onClearSelection={() => (selectedContractIds = new Set())}
/>

<DataPanel
	{columns}
	data={displayData}
	onrowclick={handleRowClick}
	loading={rentalsQuery.isPending || rentalsQuery.isFetching}
	selectable={true}
	bind:selectedIds={selectedContractIds}
	{getRowId}
/>

<div class="mt-6">
	<Pagination
		bind:currentPage
		{totalPages}
		totalItems={totalRecords}
		itemsPerPage={DEFAULT_ITEMS_PER_PAGE}
		itemLabel="contracts"
	/>
</div>
