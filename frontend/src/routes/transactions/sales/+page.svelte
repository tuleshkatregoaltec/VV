<script lang="ts">
  import { setContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import Pagination from '$lib/components/ui/Pagination.svelte';
  import { transactions as api, filters } from '$lib/api';
  import type { Transaction, FilterOptions } from '$lib/api/types';
  import { propertyType, masterProject, timeframe } from '$lib/components/filters/globalFilters.svelte';
  import {
    PROPERTY_USAGE,
    RESIDENTIAL_COLUMNS,
    COMMERCIAL_COLUMNS,
    TIMEFRAME_MAPPING,
    DEFAULT_ITEMS_PER_PAGE
  } from '$lib/constants/transactions';
  import type { FilterDefinition } from '$lib/types/filters';

  interface TransformedTransaction {
    date: string;
    project: string;
    building: string;
    propertyType: string;
    propertySubType: string;
    bedrooms: string;
    area: number;
    price: number;
    pricePerSqFt: number;
    registration: string;
    area_name: string;
  }

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
    selectedBuilding: 'All',
    selectedPropertyType: 'All',
    selectedBedroomsOrSubType: 'All',
    selectedRegistration: 'All',
    areaRange: { min: '', max: '' },
    priceRange: { min: '', max: '' },
    pricePerSqFtRange: { min: '', max: '' }
  });

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
    
    // Global filters
    if (masterProject.current !== 'All') {
      apiFilters.master_project = masterProject.current;
    }
    
    // Local dropdown filters
    if (localFilters.selectedProject !== 'All') {
      apiFilters.project = localFilters.selectedProject;
    }
    if (localFilters.selectedBuilding !== 'All') {
      apiFilters.building = localFilters.selectedBuilding;
    }
    if (localFilters.selectedPropertyType !== 'All') {
      apiFilters.property_type = localFilters.selectedPropertyType;
    }
    if (localFilters.selectedBedroomsOrSubType !== 'All') {
      if (propertyType.current === PROPERTY_USAGE.RESIDENTIAL) {
        apiFilters.rooms = localFilters.selectedBedroomsOrSubType;
      } else {
        apiFilters.property_sub_type = localFilters.selectedBedroomsOrSubType;
      }
    }
    if (localFilters.selectedRegistration !== 'All') {
      apiFilters.registration_type = localFilters.selectedRegistration;
    }
    
    // Range filters
    if (localFilters.areaRange.min) {
      apiFilters.area_min = parseFloat(localFilters.areaRange.min);
    }
    if (localFilters.areaRange.max) {
      apiFilters.area_max = parseFloat(localFilters.areaRange.max);
    }
    if (localFilters.priceRange.min) {
      apiFilters.price_min = parseFloat(localFilters.priceRange.min);
    }
    if (localFilters.priceRange.max) {
      apiFilters.price_max = parseFloat(localFilters.priceRange.max);
    }
    if (localFilters.pricePerSqFtRange.min) {
      apiFilters.price_sqft_min = parseFloat(localFilters.pricePerSqFtRange.min);
    }
    if (localFilters.pricePerSqFtRange.max) {
      apiFilters.price_sqft_max = parseFloat(localFilters.pricePerSqFtRange.max);
    }
    
    return apiFilters;
  }

  // ========================================
  // TanStack Query
  // ========================================
  
  // Main transactions query - refetches when any filter or page changes
  const transactionsQuery = createQuery(() => ({
    queryKey: [
      'sales-transactions',
      propertyType.current,
      masterProject.current,
      timeframe.current,
      currentPage,
      localFilters.selectedProject,
      localFilters.selectedBuilding,
      localFilters.selectedPropertyType,
      localFilters.selectedBedroomsOrSubType,
      localFilters.selectedRegistration,
      localFilters.areaRange.min,
      localFilters.areaRange.max,
      localFilters.priceRange.min,
      localFilters.priceRange.max,
      localFilters.pricePerSqFtRange.min,
      localFilters.pricePerSqFtRange.max,
    ],
    queryFn: () => api.sales(buildApiFilters()),
  }));

  // Filter options query - context-aware
  const filterOptionsQuery = createQuery(() => ({
    queryKey: ['filterOptions', 'sales', propertyType.current, masterProject.current, timeframe.current],
    queryFn: () => filters.sales({
      property_usage: propertyType.current,
      master_project: masterProject.current !== 'All' ? masterProject.current : undefined,
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current]
    }),
    staleTime: 5 * 60 * 1000, // 5 minutes
  }));

  // ========================================
  // Derived Values
  // ========================================
  
  let columns = $derived(
    propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? RESIDENTIAL_COLUMNS : COMMERCIAL_COLUMNS
  );

  // Filter definitions - show immediately, options load async
  const opts = $derived(filterOptionsQuery.data);
  let filterDefinitions = $derived<FilterDefinition[]>(filterOptionsQuery.data ? [
    { id: 'selectedProject', label: 'Project', type: 'searchable', options: ['All', ...(opts?.projects ?? [])] },
    { id: 'selectedBuilding', label: 'Building', type: 'searchable', options: ['All', ...(opts?.buildings ?? [])] },
    { id: 'selectedPropertyType', label: 'Property Type', type: 'standard', options: ['All', ...(opts?.property_types ?? [])] },
    { 
      id: 'selectedBedroomsOrSubType', 
      label: propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? 'Bedrooms' : 'Property Sub Type', 
      type: 'standard', 
      options: ['All', ...(propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? (opts?.rooms ?? []) : (opts?.property_sub_types ?? []))]
    },
    { id: 'selectedRegistration', label: 'Registration', type: 'standard', options: ['All', ...(opts?.registration_types ?? [])] },
    { id: 'areaRange', label: 'Area (sq.ft)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
    { id: 'priceRange', label: 'Price (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
    { id: 'pricePerSqFtRange', label: 'Price/sq.ft (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' }
  ] : []);

  function transformTransaction(t: Transaction): TransformedTransaction {
    return {
      date: t.instance_date ?? '-',
      area_name: t.area_name_en ?? '-',
      project: t.project_name_en ?? '-',
      building: t.building_name_en ?? '-',
      propertyType: t.property_type_en ?? '-',
      propertySubType: t.property_sub_type_en ?? '-',
      bedrooms: t.rooms_en ?? '-',
      area: t.procedure_area ?? 0,
      price: t.actual_worth ?? 0,
      pricePerSqFt: t.meter_sale_price ?? 0,
      registration: t.reg_type_en ?? '-',
    };
  }

  let displayData = $derived(
    transactionsQuery.data?.transactions.map(transformTransaction) ?? []
  );

  let totalRecords = $derived(transactionsQuery.data?.total ?? 0);
  let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE));

  // ========================================
  // Actions
  // ========================================
  
  function resetFilters() {
    localFilters = {
      selectedProject: 'All',
      selectedBuilding: 'All',
      selectedPropertyType: 'All',
      selectedBedroomsOrSubType: 'All',
      selectedRegistration: 'All',
      areaRange: { min: '', max: '' },
      priceRange: { min: '', max: '' },
      pricePerSqFtRange: { min: '', max: '' }
    };
    currentPage = 1;
  }

  function handleRowClick(row: TransformedTransaction) {
    console.log('Transaction clicked:', row);
  }

  // Create a derived string for filter comparison
  let filterKey = $derived(JSON.stringify(localFilters));
  
  // Track previous filter key
  let lastFilterKey = '';
  
  // Reset to page 1 when filters change (not when page changes)
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
    const _ = [propertyType.current, masterProject.current, timeframe.current];
    currentPage = 1;
    resetFilters();
  });
</script>

<div class="min-h-screen bg-background">
  <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
    {#if transactionsQuery.isError}
      <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6">
        <p class="text-red-800 font-semibold">Error loading data</p>
        <p class="text-red-600 mt-2">{transactionsQuery.error.message}</p>
        <button
          onclick={() => transactionsQuery.refetch()}
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
      {columns} 
      data={displayData} 
      onrowclick={handleRowClick}
      loading={transactionsQuery.isPending || transactionsQuery.isFetching}
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
  </div>
</div>
