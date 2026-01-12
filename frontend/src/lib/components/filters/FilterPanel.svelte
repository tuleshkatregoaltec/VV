<script lang="ts">
  import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte';
  import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte';
  import CheckboxDropdown from '$lib/components/dropdowns/CheckboxDropdown.svelte';
  import type { FilterDefinition } from '$lib/types/filters';


  // Hardcoded range options
  const AREA_OPTIONS = ["All", "<500", "500-1000", "1000-2000", "2000-5000", ">5000"];
  const PRICE_OPTIONS = ["All", "<500k", "500k-1M", "1M-2M", "2M-5M", ">5M"];
  const PRICE_SQFT_OPTIONS = ["All", "<1000", "1000-1500", "1500-2000", ">2000"];
  const ANNUAL_RENT_OPTIONS = ["All", "<50k", "50k-100k", "100k-200k", ">200k"];

  let {
    filterDefinitions = [],
    filters = $bindable({}),
    onReset = () => {},
    onExport = () => {},
    selectedCount = 0,
    onClearSelection = () => {}
  }: {
    filterDefinitions?: FilterDefinition[];
    filters?: Record<string, any>;
    onReset?: () => void;
    onExport?: () => void;
    selectedCount?: number;
    onClearSelection?: () => void;
  } = $props();

  function resetFilters() {
    filters = {};
    onReset();
  }
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 p-6 mb-6">
  <div class="flex items-center justify-between mb-6">
    <div class="flex items-center gap-4">
      <h2 class="text-xl font-bold text-gray-900">Filters</h2>
      {#if selectedCount > 0}
        <div class="flex items-center gap-2 px-3 py-1 bg-primary/10 text-primary rounded-lg text-sm font-medium">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          <span>{selectedCount} selected</span>
          <button
            onclick={onClearSelection}
            class="ml-1 hover:text-primary-dark transition-colors"
            aria-label="Clear selection"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      {/if}
    </div>
    <div class="flex items-center gap-2">
      <button
        onclick={resetFilters}
        class="text-sm px-3 py-1 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
      >
        Reset
      </button>

      <button
        onclick={onExport}
        class="inline-flex items-center gap-2 text-sm px-3 py-1 rounded-lg bg-green-600 text-white hover:bg-green-700 transition-colors"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        Export {selectedCount > 0 ? '(' + selectedCount + ')' : '(100 max)'}
      </button>
    </div>
  </div>

  <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 sm:gap-6">
    {#each filterDefinitions as filter (filter.id)}

    
      <div class="flex flex-col gap-2">
        <!-- Reverted back to <label> tag -->
        <label for="{filter.id}-input" class="block text-sm text-gray-900">
          {filter.label}
        </label>

        {#if filter.type === 'searchable'}
          <SearchableDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={filter.options || []}
            bind:value={filters[filter.id]}
          />
        {:else if filter.id === 'area'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={AREA_OPTIONS}
            bind:value={filters[filter.id]}
          />
        {:else if filter.id === 'price'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={PRICE_OPTIONS}
            bind:value={filters[filter.id]}
          />
        {:else if filter.id === 'pricePerSqFt'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={PRICE_SQFT_OPTIONS}
            bind:value={filters[filter.id]}
          />
        {:else if filter.id === 'annualRent'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={ANNUAL_RENT_OPTIONS}
            bind:value={filters[filter.id]}
          />
        {:else if filter.type === 'standard' || filter.type === 'price-range' || filter.type === 'range'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={filter.options || []}
            bind:value={filters[filter.id]}
          />
        {:else if filter.type === 'checkbox'}
          <CheckboxDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={(filter.options || []).map(o => ({ id: o, label: o }))}
            bind:selected={filters[filter.id]}
          />
        {/if}
      </div>
    {/each}
  </div>
</div>
