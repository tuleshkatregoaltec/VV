<script lang="ts">
  import { setContext } from 'svelte';
  import { createQuery } from '@tanstack/svelte-query';
  import DataPanel from '$lib/components/transactions/DataPanel.svelte';
  import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
  import Pagination from '$lib/components/ui/Pagination.svelte';
  import { transactions as api } from '$lib/api/transactions';
  import { filters } from '$lib/api/filters';
  import type { RentalContract } from '$lib/api/transactions';
  import { propertyType, masterProject, timeframe } from '$lib/components/filters/globalFilters.svelte';
  import {
    TIMEFRAME_MAPPING,
    DEFAULT_ITEMS_PER_PAGE
  } from '$lib/constants/transactions';
  import type { FilterDefinition } from '$lib/types/filters';

  // Area in sq.m (database stores in sqm)
  const AREA_OPTIONS = ["All", "<50", "50-100", "100-200", "200-500", ">500"];
  const ANNUAL_RENT_OPTIONS = ["All", "<50k", "50k-100k", "100k-200k", ">200k"];

  interface TransformedRental {
    contract_id: string;
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
    { id: 'area', label: 'Area (sq.m)', align: 'right' as const, format: (val: number) => val.toLocaleString() },
    { id: 'annualRent', label: 'Annual Rent (AED)', align: 'right' as const, highlighted: true, format: (val: number) => val.toLocaleString() },
    { id: 'registration', label: 'Reg Type', align: 'left' as const }
  ];

  // Dropdown context is provided by transactions/+layout.svelte

  // ========================================
  // Local State
  // ========================================
  let currentPage = $state(1);
  let selectedContractIds = $state(new Set<string>());

  let localFilters = $state({
    selectedProject: 'All',
    selectedPropertyType: 'All',
    selectedPropertySubType: 'All',
    selectedTenantType: 'All',
    selectedRegistration: 'All',
    areaRange: 'All',      // ✅ String, not object
    rentRange: 'All'       // ✅ String, not object
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
    
    // Range filters are now strings - let the API client handle conversion
    // The transactions.ts client converts these via rangeMap
    if (localFilters.areaRange !== 'All') {
      apiFilters.area = localFilters.areaRange;
    }
    if (localFilters.rentRange !== 'All') {
      apiFilters.annualRent = localFilters.rentRange;
    }
    
    return apiFilters;
  }

  // ========================================
  // TanStack Queries
  // ========================================
  
  // Main rentals query
  const rentalsQuery = createQuery(() => ({
    queryKey: [
      'rental-contracts',
      propertyType.current,
      masterProject.current,
      timeframe.current,
      currentPage,
      localFilters.selectedProject,
      localFilters.selectedPropertyType,
      localFilters.selectedPropertySubType,
      localFilters.selectedTenantType,
      localFilters.selectedRegistration,
      localFilters.areaRange,
      localFilters.rentRange,
    ],
    queryFn: () => api.rentals(buildApiFilters()),
  }));

  // Filter options query - ALWAYS includes property_usage and timeframe_days
  const filterOptionsQuery = createQuery(() => ({
    queryKey: [
      'filterOptions',
      'rentals',
      propertyType.current,
      masterProject.current,
      timeframe.current,
      localFilters.selectedProject,
      localFilters.selectedPropertyType,
      localFilters.selectedPropertySubType,
      localFilters.selectedTenantType,
      localFilters.selectedRegistration,
    ],
    queryFn: () => {
      const filterParams: Record<string, any> = {
        property_usage: propertyType.current,
        timeframe_days: TIMEFRAME_MAPPING[timeframe.current]
      };
      
      // Add active filters for context-aware options
      if (masterProject.current !== 'All') {
        filterParams.master_project = masterProject.current;
      }
      if (localFilters.selectedProject !== 'All') {
        filterParams.project = localFilters.selectedProject;
      }
      if (localFilters.selectedPropertyType !== 'All') {
        filterParams.property_type = localFilters.selectedPropertyType;
      }
      if (localFilters.selectedPropertySubType !== 'All') {
        filterParams.property_sub_type = localFilters.selectedPropertySubType;
      }
      if (localFilters.selectedTenantType !== 'All') {
        filterParams.tenant_type = localFilters.selectedTenantType;
      }
      if (localFilters.selectedRegistration !== 'All') {
        filterParams.contract_reg_type = localFilters.selectedRegistration;
      }
      
      return filters.rentals(filterParams);
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
  }));

  // ========================================
  // Derived Values
  // ========================================
  
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
        id: 'selectedPropertyType', 
        label: 'Property Type', 
        type: 'standard', 
        options: ['All', ...(opts.property_types ?? [])] 
      },
      { 
        id: 'selectedPropertySubType', 
        label: 'Sub Type', 
        type: 'standard', 
        options: ['All', ...(opts.property_sub_types ?? [])] 
      },
      { 
        id: 'selectedTenantType', 
        label: 'Tenant Type', 
        type: 'standard', 
        options: ['All', ...(opts.tenant_types ?? [])] 
      },
      { 
        id: 'selectedRegistration', 
        label: 'Reg Type', 
        type: 'standard', 
        options: ['All', ...(opts.contract_reg_types ?? [])] 
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
    ] : []
  );

  function transformRental(r: RentalContract): TransformedRental {
    return {
      contract_id: r.contract_id,
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

  function getRowId(row: TransformedRental): string {
    return row.contract_id;
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
      areaRange: 'All',   // ✅ String
      rentRange: 'All'    // ✅ String
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
  let filterKey = $derived(JSON.stringify({
    project: localFilters.selectedProject,
    propertyType: localFilters.selectedPropertyType,
    propertySubType: localFilters.selectedPropertySubType,
    tenantType: localFilters.selectedTenantType,
    registration: localFilters.selectedRegistration,
    areaRange: localFilters.areaRange,
    rentRange: localFilters.rentRange
  }));
  
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
    const _ = [propertyType.current, masterProject.current, timeframe.current];
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
  <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6">
    <p class="text-red-800 font-semibold">Error loading data</p>
    <p class="text-red-600 mt-2">{rentalsQuery.error?.message ?? 'Unknown error'}</p>
    <button
      onclick={() => rentalsQuery.refetch()}
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
  selectedCount={selectedContractIds.size}
  onClearSelection={() => selectedContractIds = new Set()}
/>

<DataPanel
  columns={RENTAL_COLUMNS}
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
