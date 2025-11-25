<script lang="ts">
  import { setContext, onMount } from 'svelte';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import TransactionPagination from '$lib/components/transactions/TransactionPagination.svelte';
  import { transactionStore } from '$lib/stores/transactions.svelte';
  import { filters } from '$lib/api';
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
  
  let filterOptions = $state<FilterOptions | null>(null);
  let error = $state<string | null>(null);
  let currentPage = $state(1);
  let isInitialized = $state(false);
  let isBackfilling = $state(false);
  let backfillTimer: ReturnType<typeof setTimeout> | null = null;

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
  // Derived Values
  // ========================================
  let columns = $derived(
    propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? RESIDENTIAL_COLUMNS : COMMERCIAL_COLUMNS
  );

  let filterDefinitions = $derived<FilterDefinition[]>(
    filterOptions ? [
      { id: 'selectedProject', label: 'Project', type: 'searchable', options: ['All', ...filterOptions.projects] },
      { id: 'selectedBuilding', label: 'Building', type: 'searchable', options: ['All', ...filterOptions.buildings] },
      { id: 'selectedPropertyType', label: 'Property Type', type: 'standard', options: ['All', ...filterOptions.property_types] },
      { 
        id: 'selectedBedroomsOrSubType', 
        label: propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? 'Bedrooms' : 'Property Sub Type', 
        type: 'standard', 
        options: ['All', ...(propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? filterOptions.rooms : filterOptions.property_sub_types)]
      },
      { id: 'selectedRegistration', label: 'Registration', type: 'standard', options: ['All', ...filterOptions.registration_types] },
      { id: 'areaRange', label: 'Area (sq.ft)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
      { id: 'priceRange', label: 'Price (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' },
      { id: 'pricePerSqFtRange', label: 'Price/sq.ft (AED)', type: 'price-range', placeholderMin: 'Min', placeholderMax: 'Max' }
    ] : []
  );

  // Transform once, filter on transformed data
  let transformedCache = $derived(
    transactionStore.cache.map(transformTransaction)
  );

  let displayData = $derived.by(() => {
    return transformedCache.filter((t) => {
      if (localFilters.selectedProject !== 'All' && t.project !== localFilters.selectedProject) return false;
      if (localFilters.selectedBuilding !== 'All' && t.building !== localFilters.selectedBuilding) return false;
      if (localFilters.selectedPropertyType !== 'All' && t.propertyType !== localFilters.selectedPropertyType) return false;
      
      const bedroomField = propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? t.bedrooms : t.propertySubType;
      if (localFilters.selectedBedroomsOrSubType !== 'All' && bedroomField !== localFilters.selectedBedroomsOrSubType) return false;
      
      if (localFilters.selectedRegistration !== 'All' && t.registration !== localFilters.selectedRegistration) return false;
      
      if (localFilters.areaRange.min && t.area < parseFloat(localFilters.areaRange.min)) return false;
      if (localFilters.areaRange.max && t.area > parseFloat(localFilters.areaRange.max)) return false;
      if (localFilters.priceRange.min && t.price < parseFloat(localFilters.priceRange.min)) return false;
      if (localFilters.priceRange.max && t.price > parseFloat(localFilters.priceRange.max)) return false;
      if (localFilters.pricePerSqFtRange.min && t.pricePerSqFt < parseFloat(localFilters.pricePerSqFtRange.min)) return false;
      if (localFilters.pricePerSqFtRange.max && t.pricePerSqFt > parseFloat(localFilters.pricePerSqFtRange.max)) return false;
      
      return true;
    });
  });

  let totalRecords = $derived(transactionStore.totalCount);
  let totalPages = $derived(Math.ceil(totalRecords / DEFAULT_ITEMS_PER_PAGE));
  let paginatedData = $derived(
    displayData.slice((currentPage - 1) * DEFAULT_ITEMS_PER_PAGE, currentPage * DEFAULT_ITEMS_PER_PAGE)
  );

  // ========================================
  // Helper Functions
  // ========================================
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

  function buildGlobalFilters() {
    return {
      property_usage: propertyType.current,
      master_project: masterProject.current !== 'All' ? masterProject.current : undefined,
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current],
      limit: CACHE_SIZE,
      offset: 0
    };
  }

  function buildAllFilters() {
    const allFilters: Record<string, any> = {
      property_usage: propertyType.current,
      timeframe_days: TIMEFRAME_MAPPING[timeframe.current],
      limit: CACHE_SIZE
    };
    
    // Add global filters
    if (masterProject.current !== 'All') {
      allFilters.master_project = masterProject.current;
    }
    
    // Add local filters (send to backend!)
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

  // ========================================
  // API Functions
  // ========================================
  async function loadData() {
    transactionStore.reset();
    error = null;
    
    try {
      await Promise.all([
        transactionStore.load(buildGlobalFilters()),
        filters.sales().then(opts => filterOptions = opts)
      ]);
    } catch (e) {
      error = e instanceof Error ? e.message : 'Failed to load data';
      console.error('Error loading data:', e);
    }
  }

  function checkBackfill() {
    if (backfillTimer) clearTimeout(backfillTimer);
    
    if (isBackfilling || transactionStore.loading) return;
    
    backfillTimer = setTimeout(async () => {
      if (displayData.length < DEFAULT_ITEMS_PER_PAGE && transactionStore.hasMore) {
        isBackfilling = true;
        try {
          // Use ALL filters (global + local) for server-side filtering
          await transactionStore.loadMore(buildAllFilters());
        } finally {
          isBackfilling = false;
        }
      }
    }, 500);
  }

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

  // ========================================
  // Lifecycle
  // ========================================
  onMount(async () => {
    await loadData();
    isInitialized = true;
  });

  $effect(() => {
    const _ = [propertyType.current, masterProject.current, timeframe.current];
    
    if (!isInitialized) return;
    
    currentPage = 1;
    resetFilters();
    loadData();
  });
  
  $effect(() => {
    const count = displayData.length;
    
    if (!isInitialized) return;
    
    checkBackfill();
  });
</script>

<div class="min-h-screen bg-background">
  <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
    {#if transactionStore.loading && transactionStore.cacheSize === 0}
      <div class="flex items-center justify-center py-20">
        <div class="text-center">
          <div class="inline-block animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
          <p class="mt-4 text-gray-600">Loading transactions...</p>
          <p class="mt-2 text-sm text-gray-500">Fetching {CACHE_SIZE} records...</p>
        </div>
      </div>
    {:else if error}
      <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
        <p class="text-red-800 font-semibold">Error loading data</p>
        <p class="text-red-600 mt-2">{error}</p>
        <button
          onclick={loadData}
          class="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
        >
          Retry
        </button>
      </div>
    {:else}
      <div class="mb-4 flex justify-between items-center">
        <span class="text-sm text-gray-600">
          Showing {totalRecords.toLocaleString()} of {transactionStore.cacheSize.toLocaleString()} cached
          <span class="text-gray-400">({transactionStore.totalCount.toLocaleString()} total in DB)</span>
        </span>
        
        <div class="flex items-center gap-3">
          {#if isBackfilling}
            <span class="text-xs text-blue-600 animate-pulse">• Auto-loading more...</span>
          {/if}
          
          {#if transactionStore.hasMore}
            <button
              onclick={() => transactionStore.loadMore(buildAllFilters())}
              disabled={transactionStore.loading}
              class="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
            >
              {transactionStore.loading ? 'Loading...' : 'Manual Load More'}
            </button>
          {:else}
            <span class="text-sm text-green-600">✓ All data cached</span>
          {/if}
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
