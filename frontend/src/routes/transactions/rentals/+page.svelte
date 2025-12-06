<script lang="ts">
  import { setContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import Pagination from '$lib/components/ui/Pagination.svelte';
  import { transactions as api, filters } from '$lib/api';
  import type { RentalContract } from '$lib/api/types';
  import { masterProject, timeframe } from '$lib/components/filters/globalFilters.svelte';
  import {
    TIMEFRAME_MAPPING,
    DEFAULT_ITEMS_PER_PAGE
  } from '$lib/constants/transactions';
  import type { FilterDefinition } from '$lib/types/filters';

  interface TransformedRental {
    date: string;
    project: string;
    propertyType: string;
    propertySubType: string;
    tenantType: string;
    area: number;
    annualRent: number;
    registration: string;
    area_name: string;
  }

  // Column configuration for rentals
  const RENTAL_COLUMNS = [
    { id: 'date', label: 'Start Date', align: 'left' as const },
    { id: 'area_name', label: 'Area', align: 'left' as const },
    { id: 'project', label: 'Project', align: 'left' as const },
    { id: 'propertyType', label: 'Property Type', align: 'left' as const },
    { id: 'propertySubType', label: 'Sub Type', align: 'left' as const },
    { id: 'tenantType', label: 'Tenant Type', align: 'left' as const, badge: true },
    { id: 'area', label: 'Area (sq.ft)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
    { id: 'annualRent', label: 'Annual Rent (AED)', align: 'right' as const, highlighted: true, format: (val: number) => val.toLocaleString() },
    { id: 'registration', label: 'Reg Type', align: 'left' as const }
  ];

  // Dropdown context for filter panel
  let openDropdownId = $state<string | null>(null);
  setContext('openDropdownId', {
    get value() { return openDropdownId; },
    set value(v: string | null) { openDropdownId = v; }
  });

  // State
  let currentPage = $state(1);

  let localFilters = $state({
    selectedProject: 'All',
    selectedPropertyType: 'All',
    selectedPropertySubType: 'All',
    selectedTenantType: 'All',
    selectedRegistration: 'All',
    areaRange: { min: '', max: '' },
    rentRange: { min: '', max: '' }
  });

  // ========================================
  // Build API Filters
  // ========================================
  function buildApiFilters() {
    const apiFilters: Record<string, any> = {
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current],
      limit: DEFAULT_ITEMS_PER_PAGE,
      offset: (currentPage - 1) * DEFAULT_ITEMS_PER_PAGE
    };
    
    // Global filters
    if (masterProject.current !== 'All') {
      apiFilters.master_project = masterProject.current;
    }
    
    // Local dropdown filters
    if (localFilters.selectedProject !== 'All') {
      apiFilters.project = localFilters.selectedProject;
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
    if (localFilters.areaRange.min) {
      apiFilters.area_min = parseFloat(localFilters.areaRange.min);
    }
    if (localFilters.areaRange.max) {
      apiFilters.area_max = parseFloat(localFilters.areaRange.max);
    }
    if (localFilters.rentRange.min) {
      apiFilters.rent_min = parseFloat(localFilters.rentRange.min);
    }
    if (localFilters.rentRange.max) {
      apiFilters.rent_max = parseFloat(localFilters.rentRange.max);
    }
    
    return apiFilters;
  }

  // ========================================
  // TanStack Query
  // ========================================
  
  // Main rentals query - refetches when any filter or page changes
  const rentalsQuery = createQuery(() => ({
    queryKey: [
      'rental-contracts',
      masterProject.current,
      timeframe.current,
      currentPage,
      localFilters.selectedProject,
      localFilters.selectedPropertyType,
      localFilters.selectedPropertySubType,
      localFilters.selectedTenantType,
      localFilters.selectedRegistration,
      localFilters.areaRange.min,
      localFilters.areaRange.max,
      localFilters.rentRange.min,
      localFilters.rentRange.max,
    ],
    queryFn: () => api.rentals(buildApiFilters()),
  }));

  // Filter options query - context-aware
  const filterOptionsQuery = createQuery(() => ({
    queryKey: ['filterOptions', 'rentals', masterProject.current, timeframe.current],
    queryFn: () => filters.rentals({
      master_project: masterProject.current !== 'All' ? masterProject.current : undefined,
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current]
    }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  }));

  // ========================================
  // Derived Values
  // ========================================
  
  // Filter definitions - show immediately, options load async
  const opts = $derived(filterOptionsQuery.data);
  let filterDefinitions = $derived<FilterDefinition[]>(filterOptionsQuery.data ? [
    { id: 'selectedProject', label: 'Project', type: 'searchable', options: ['All', ...(opts?.projects ?? [])] },
    { id: 'selectedPropertyType', label: 'Property Type', type: 'standard', options: ['All', ...(opts?.property_types ?? [])] },
    { id: 'selectedPropertySubType', label: 'Sub Type', type: 'standard', options: ['All', ...(opts?.property_sub_types ?? [])] },
    { id: 'selectedTenantType', label: 'Tenant Type', type: 'standard', options: ['All', ...(opts?.tenant_types ?? [])] },
    { id: 'selectedRegistration', label: 'Reg Type', type: 'standard', options: ['All', ...(opts?.contract_reg_types ?? [])] },
    { id: 'areaRange', label: 'Area (sq.ft)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
    { id: 'rentRange', label: 'Annual Rent (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' }
  ] : []);

  function transformRental(r: RentalContract): TransformedRental {
    return {
      date: r.contract_start_date ?? '-',
      area_name: r.area_name_en ?? '-',
      project: r.project_name_en ?? '-',
      propertyType: r.ejari_property_type_en ?? '-',
      propertySubType: r.ejari_property_sub_type_en ?? '-',
      tenantType: r.tenant_type_en ?? '-',
      area: r.actual_area ?? 0,
      annualRent: r.annual_amount ?? 0,
      registration: r.contract_reg_type_en ?? '-',
    };
  }

  let displayData = $derived(
    rentalsQuery.data?.contracts.map(transformRental) ?? []
  );

  let totalRecords = $derived(rentalsQuery.data?.total ?? 0);
  let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE));

  // ========================================
  // Actions
  // ========================================
  
  function resetFilters() {
    localFilters = {
      selectedProject: 'All',
      selectedPropertyType: 'All',
      selectedPropertySubType: 'All',
      selectedTenantType: 'All',
      selectedRegistration: 'All',
      areaRange: { min: '', max: '' },
      rentRange: { min: '', max: '' }
    };
    currentPage = 1;
  }

  function handleRowClick(row: TransformedRental) {
    console.log('Contract clicked:', row);
  }

  // Create a derived string for filter comparison
  let filterKey = $derived(JSON.stringify(localFilters));
  
  // Track previous filter key
  let lastFilterKey = '';
  
  // Reset to page 1 when filters change
  $effect(() => {
    if (filterKey !== lastFilterKey) {
      if (lastFilterKey !== '') {
        // Only reset page after initial load
        currentPage = 1;
      }
      lastFilterKey = filterKey;
    }
  });

  // Reset page on global filter changes
  $effect(() => {
    const _ = [masterProject.current, timeframe.current];
    currentPage = 1;
    resetFilters();
  });
</script>

<div class="min-h-screen bg-background">
  <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
    {#if rentalsQuery.isError}
      <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6">
        <p class="text-red-800 font-semibold">Error loading data</p>
        <p class="text-red-600 mt-2">{rentalsQuery.error.message}</p>
        <button
          onclick={() => rentalsQuery.refetch()}
          class="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
        >
          Retry
        </button>
      </div>
    {/if}

    {#if filterOptionsQuery.isPending}
      <div class="flex items-center justify-center py-12">
        <div class="inline-block animate-spin rounded-full h-10 w-10 border-b-2 border-primary"></div>
        <span class="ml-4 text-gray-500">Loading filters...</span>
      </div>
    {:else}
      <FilterPanel
        {filterDefinitions}
        bind:filters={localFilters}
        onReset={resetFilters}
      />
    {/if}

    <DataPanel 
      columns={RENTAL_COLUMNS} 
      data={displayData} 
      onrowclick={handleRowClick}
      loading={rentalsQuery.isPending || rentalsQuery.isFetching}
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
  </div>
</div>
