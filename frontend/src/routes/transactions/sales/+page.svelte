<script lang="ts">
  import { setContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import Pagination from '$lib/components/ui/Pagination.svelte';
  import { transactions as api } from '$lib/api/transactions';
  import { filters } from '$lib/api/filters';
  import type { Transaction } from '$lib/api/types';
  import { propertyType, masterProject, timeframe } from '$lib/components/filters/globalFilters.svelte';
  import {
    PROPERTY_USAGE,
    RESIDENTIAL_COLUMNS,
    COMMERCIAL_COLUMNS,
    TIMEFRAME_MAPPING,
    DEFAULT_ITEMS_PER_PAGE
  } from '$lib/constants/transactions';
  import type { FilterDefinition } from '$lib/types/filters';

  const AREA_OPTIONS = ["All", "<500", "500-1000", "1000-2000", "2000-5000", ">5000"];
  const PRICE_OPTIONS = ["All", "<500k", "500k-1M", "1M-2M", "2M-5M", ">5M"];
  const PRICE_SQFT_OPTIONS = ["All", "<1000", "1000-1500", "1500-2000", ">2000"];

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

  // Dropdown context is provided by transactions/+layout.svelte

  let currentPage = $state(1);

  let localFilters = $state({
    selectedProject: 'All',
    selectedBuilding: 'All',
    selectedPropertyType: 'All',
    selectedBedroomsOrSubType: 'All',
    selectedRegistration: 'All',
    areaRange: 'All',
    priceRange: 'All',
    pricePerSqFtRange: 'All'
  });


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
    
    if (localFilters.areaRange !== 'All') {
      apiFilters.area = localFilters.areaRange;
    }
    if (localFilters.priceRange !== 'All') {
      apiFilters.price = localFilters.priceRange;
    }
    if (localFilters.pricePerSqFtRange !== 'All') {
      apiFilters.pricePerSqFt = localFilters.pricePerSqFtRange;
    }
    
    return apiFilters;
  }
  
  // Main transactions query
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
      localFilters.areaRange,
      localFilters.priceRange,
      localFilters.pricePerSqFtRange,
    ],
    queryFn: () => api.sales(buildApiFilters()),
  }));

  const filterOptionsQuery = createQuery(() => ({
    queryKey: [
      'filterOptions', 
      'sales', 
      propertyType.current, 
      masterProject.current, 
      timeframe.current,
      localFilters.selectedProject,
      localFilters.selectedBuilding,
      localFilters.selectedPropertyType,
      localFilters.selectedBedroomsOrSubType,
      localFilters.selectedRegistration,
    ],
    queryFn: () => {
      const filterParams: Record<string, any> = {
        property_usage: propertyType.current,
        timeframe_days: TIMEFRAME_MAPPING[timeframe.current]
      };
      
      if (masterProject.current !== 'All') {
        filterParams.master_project = masterProject.current;
      }
      if (localFilters.selectedProject !== 'All') {
        filterParams.project = localFilters.selectedProject;
      }
      if (localFilters.selectedBuilding !== 'All') {
        filterParams.building = localFilters.selectedBuilding;
      }
      if (localFilters.selectedPropertyType !== 'All') {
        filterParams.property_type = localFilters.selectedPropertyType;
      }
      if (localFilters.selectedBedroomsOrSubType !== 'All') {
        if (propertyType.current === PROPERTY_USAGE.RESIDENTIAL) {
          filterParams.rooms = localFilters.selectedBedroomsOrSubType;
        } else {
          filterParams.property_sub_type = localFilters.selectedBedroomsOrSubType;
        }
      }
      if (localFilters.selectedRegistration !== 'All') {
        filterParams.registration_type = localFilters.selectedRegistration;
      }
      
      return filters.sales(filterParams);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  }));


  let columns = $derived(
    propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? RESIDENTIAL_COLUMNS : COMMERCIAL_COLUMNS
  );

  const opts = $derived(filterOptionsQuery.data);
  
  let filterDefinitions = $derived<FilterDefinition[]>(
    opts ? [
      { 
        id: 'selectedProject', 
        label: 'Project', 
        type: 'searchable', 
        options: ['All', ...(opts.projects ?? [])] 
      },
      { 
        id: 'selectedBuilding', 
        label: 'Building', 
        type: 'searchable', 
        options: ['All', ...(opts.buildings ?? [])] 
      },
      { 
        id: 'selectedPropertyType', 
        label: 'Property Type', 
        type: 'standard', 
        options: ['All', ...(opts.property_types ?? [])] 
      },
      { 
        id: 'selectedBedroomsOrSubType', 
        label: propertyType.current === PROPERTY_USAGE.RESIDENTIAL ? 'Bedrooms' : 'Sub Type', 
        type: 'standard', 
        options: ['All', ...(
          propertyType.current === PROPERTY_USAGE.RESIDENTIAL 
            ? (opts.rooms ?? []) 
            : (opts.property_sub_types ?? [])
        )]
      },
      { 
        id: 'selectedRegistration', 
        label: 'Registration', 
        type: 'standard', 
        options: ['All', ...(opts.registration_types ?? [])] 
      },
      { 
        id: 'areaRange', 
        label: 'Area (sq.ft)', 
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
        id: 'pricePerSqFtRange', 
        label: 'Price/sq.ft (AED)', 
        type: 'standard',
        options: PRICE_SQFT_OPTIONS
      }
    ] : []
  );

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


  function resetFilters() {
    localFilters = {
      selectedProject: 'All',
      selectedBuilding: 'All',
      selectedPropertyType: 'All',
      selectedBedroomsOrSubType: 'All',
      selectedRegistration: 'All',
      areaRange: 'All',
      priceRange: 'All',
      pricePerSqFtRange: 'All'
    };
    currentPage = 1;
  }

  function handleRowClick(row: TransformedTransaction) {
    console.log('Transaction clicked:', row);
  }

  // Track filter changes to reset page
  let filterKey = $derived(JSON.stringify({
    project: localFilters.selectedProject,
    building: localFilters.selectedBuilding,
    propertyType: localFilters.selectedPropertyType,
    bedroomsOrSubType: localFilters.selectedBedroomsOrSubType,
    registration: localFilters.selectedRegistration,
    areaRange: localFilters.areaRange,
    priceRange: localFilters.priceRange,
    pricePerSqFtRange: localFilters.pricePerSqFtRange
  }));
  
  let lastFilterKey = '';
  
  // Reset to page 1 when filters change
  $effect(() => {
    if (filterKey !== lastFilterKey) {
      if (lastFilterKey !== '') {
        currentPage = 1;
      }
      lastFilterKey = filterKey;
    }
  });

  // Reset page and filters on global filter changes
  $effect(() => {
    const _ = [propertyType.current, masterProject.current, timeframe.current];
    currentPage = 1;
    resetFilters();
  });

  let isExporting = $state(false);
  
  async function handleExport() {
    isExporting = true;
    try {
      const filters = buildApiFilters();
      
      const blob = await api.exportSales(filters);
      
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `sales_export_${Date.now()}.xlsx`;
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

{#if transactionsQuery.isError}
  <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6">
    <p class="text-red-800 font-semibold">Error loading data</p>
    <p class="text-red-600 mt-2">{transactionsQuery.error?.message ?? 'Unknown error'}</p>
    <button
      onclick={() => transactionsQuery.refetch()}
      class="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
    >
      Retry
    </button>
  </div>
{/if}

<FilterPanel
  {filterDefinitions}
  bind:filters={localFilters}
  onReset={resetFilters}
  onExport={handleExport}
/> 

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
