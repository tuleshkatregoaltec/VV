<script lang="ts">
  import { setContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import TransactionPagination from '$lib/components/transactions/TransactionPagination.svelte';
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

  let openDropdownId = $state<string | null>(null);
  setContext('openDropdownId', {
    get value() { return openDropdownId; },
    set value(v: string | null) { openDropdownId = v; }
  });

  const CACHE_SIZE = 250;
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
  // TanStack Query Setup
  // ========================================
  
  // Helper to build filters for API
  function buildAllFilters() {
    const allFilters: Record<string, any> = {
      property_usage: propertyType.current,
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current],
      limit: CACHE_SIZE,
      offset: 0
    };
    
    if (masterProject.current !== 'All') {
      allFilters.master_project = masterProject.current;
    }
    
    // Local filters
    if (localFilters.selectedProject !== 'All') {
      allFilters.project = localFilters.selectedProject;
    }
    if (localFilters.selectedBuilding !== 'All') {
      allFilters.building = localFilters.selectedBuilding;
    }
    if (localFilters.selectedPropertyType !== 'All') {
      allFilters.property_type = localFilters.selectedPropertyType;
    }
    if (localFilters.selectedBedroomsOrSubType !== 'All') {
      allFilters.rooms = localFilters.selectedBedroomsOrSubType;
    }
    if (localFilters.selectedRegistration !== 'All') {
      allFilters.registration_type = localFilters.selectedRegistration;
    }
    
    return allFilters;
  }

  // Main transactions query - AUTOMATICALLY refetches when queryKey changes!
  const transactionsQuery = createQuery(() => ({
    queryKey: [
      'transactions',
      propertyType.current,
      masterProject.current,
      timeframe.current,
      localFilters.selectedProject,
      localFilters.selectedBuilding,
      localFilters.selectedPropertyType,
      localFilters.selectedBedroomsOrSubType,
      localFilters.selectedRegistration,
    ],
    queryFn: async () => {
      const response = await api.sales(buildAllFilters());
      return response;
    },
  }));

  // Filter options query (cached separately)
  const filterOptionsQuery = createQuery(() => ({
    queryKey: ['filterOptions', 'sales'],
    queryFn: () => filters.sales(),
    staleTime: 24 * 60 * 60 * 1000, // 24 hours
  }));

  // ========================================
  // Derived Values
  // ========================================
  
  let columns = $derived(
    propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? RESIDENTIAL_COLUMNS : COMMERCIAL_COLUMNS
  );

  let filterDefinitions = $derived<FilterDefinition[]>(
    filterOptionsQuery.data ? [
      { id: 'selectedProject', label: 'Project', type: 'searchable', options: ['All', ...filterOptionsQuery.data.projects] },
      { id: 'selectedBuilding', label: 'Building', type: 'searchable', options: ['All', ...filterOptionsQuery.data.buildings] },
      { id: 'selectedPropertyType', label: 'Property Type', type: 'standard', options: ['All', ...filterOptionsQuery.data.property_types] },
      { 
        id: 'selectedBedroomsOrSubType', 
        label: propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? 'Bedrooms' : 'Property Sub Type', 
        type: 'standard', 
        options: ['All', ...(propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? filterOptionsQuery.data.rooms : filterOptionsQuery.data.property_sub_types)]
      },
      { id: 'selectedRegistration', label: 'Registration', type: 'standard', options: ['All', ...filterOptionsQuery.data.registration_types] },
      { id: 'areaRange', label: 'Area (sq.ft)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
      { id: 'priceRange', label: 'Price (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
      { id: 'pricePerSqFtRange', label: 'Price/sq.ft (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' }
    ] : []
  );

  function transformTransaction(t: Transaction): TransformedTransaction {
    return {
      date: t.instance_date ?? '-',
      area_name: t.area_name ?? '-',
      project: t.project_name ?? '-',
      building: t.building_name ?? '-',
      propertyType: t.property_type ?? '-',
      propertySubType: t.property_sub_type ?? '-',
      bedrooms: t.rooms_description ?? '-',
      area: t.procedure_area ?? 0,
      price: t.actual_worth ?? 0,
      pricePerSqFt: t.meter_sale_price ?? 0,
      registration: t.reg_type ?? '-',
    };
  }

  // Transform and filter data client-side for instant UX
  let transformedCache = $derived(
    transactionsQuery.data?.transactions.map(transformTransaction) ?? []
  );

  let displayData = $derived.by(() => {
    return transformedCache.filter((t) => {
      // Client-side range filters only (server handles dropdowns)
      if (localFilters.areaRange.min && t.area < parseFloat(localFilters.areaRange.min)) return false;
      if (localFilters.areaRange.max && t.area > parseFloat(localFilters.areaRange.max)) return false;
      if (localFilters.priceRange.min && t.price < parseFloat(localFilters.priceRange.min)) return false;
      if (localFilters.priceRange.max && t.price > parseFloat(localFilters.priceRange.max)) return false;
      if (localFilters.pricePerSqFtRange.min && t.pricePerSqFt < parseFloat(localFilters.pricePerSqFtRange.min)) return false;
      if (localFilters.pricePerSqFtRange.max && t.pricePerSqFt > parseFloat(localFilters.pricePerSqFtRange.max)) return false;
      
      return true;
    });
  });

  let totalRecords = $derived(transactionsQuery.data?.total ?? 0);
  let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE));
  
  let paginatedData = $derived(
    displayData.slice((currentPage - 1) * DEFAULT_ITEMS_PER_PAGE, currentPage * DEFAULT_ITEMS_PER_PAGE)
  );

  // ========================================
  // Helper Functions
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
    // TanStack Query automatically refetches when queryKey changes!
  }

  function handleRowClick(row: TransformedTransaction) {
    console.log('Transaction clicked:', row);
  }

  // Reset page when filters change
  $effect(() => {
    const _ = [
      localFilters.selectedProject,
      localFilters.selectedBuilding,
      localFilters.selectedPropertyType,
      localFilters.selectedBedroomsOrSubType,
      localFilters.selectedRegistration,
    ];
    currentPage = 1;
  });
</script>

<div class="min-h-screen bg-background">
  <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
    {#if transactionsQuery.isPending}
      <div class="flex items-center justify-center py-20">
        <div class="text-center">
          <div class="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          <p class="mt-4 text-gray-600">Loading transactions...</p>
          <p class="mt-2 text-sm text-gray-500">Fetching {CACHE_SIZE} records...</p>
        </div>
      </div>
    {:else if transactionsQuery.isError}
      <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
        <p class="text-red-800 font-semibold">Error loading data</p>
        <p class="text-red-600 mt-2">{transactionsQuery.error.message}</p>
        <button
          onclick={() => transactionsQuery.refetch()}
          class="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
        >
          Retry
        </button>
      </div>
    {:else}
      <div class="mb-4 flex justify-between items-center">
        <span class="text-sm text-gray-600">
          Showing {displayData.length.toLocaleString()} of {transformedCache.length.toLocaleString()} cached
          <span class="text-gray-400">({totalRecords.toLocaleString()} total in DB)</span>
        </span>
        
        <div class="flex items-center gap-3">
          {#if transactionsQuery.isFetching}
            <span class="text-xs text-blue-600 animate-pulse">• Refetching...</span>
          {/if}
          
          <button
            onclick={() => transactionsQuery.refetch()}
            disabled={transactionsQuery.isFetching}
            class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {transactionsQuery.isFetching ? 'Loading...' : 'Refresh Data'}
          </button>
        </div>
      </div>

      <FilterPanel
        {filterDefinitions}
        bind:filters={localFilters}
        onReset={resetFilters}
      />

      <DataPanel 
        {columns} 
        data={paginatedData} 
        onrowclick={handleRowClick} 
      />

      <div class="mt-6">
        <TransactionPagination
          bind:currentPage
          {totalPages}
          {totalRecords}
          itemsPerPage={DEFAULT_ITEMS_PER_PAGE}
        />
      </div>
    {/if}
  </div>
</div>
