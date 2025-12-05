<script lang="ts">
  import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte';
  import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte';
  import PriceRangeDropdown from '$lib/components/dropdowns/PriceRangeDropdown.svelte';
  import CheckboxDropdown from '$lib/components/dropdowns/CheckboxDropdown.svelte';
  import type { FilterDefinition } from '$lib/types/filters';

  let {
    filterDefinitions = [],
    filters = $bindable({}),
    onReset
  }: {
    filterDefinitions?: FilterDefinition[];
    filters?: Record<string, any>;
    onReset?: () => void;
  } = $props();

  function resetFilters() {
    filters = {};
    onReset?.();
  }
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 p-6 mb-6">
  <div class="flex items-center justify-between mb-6">
    <h2 class="text-xl font-bold text-gray-900">Filters</h2>
    <button
      onclick={resetFilters}
      class="text-sm px-3 py-1 rounded-lg border border-gray-300 text-gray-700 hover:bg-gray-50 transition-colors"
    >
      Reset
    </button>
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
        {:else if filter.type === 'standard'}
          <StandardDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            options={filter.options || []}
            bind:value={filters[filter.id]}
          />
        {:else if filter.type === 'price-range'}
          <PriceRangeDropdown
            id="{filter.id}-input"
            ariaLabel={filter.label}
            placeholderMin={filter.placeholderMin}
            placeholderMax={filter.placeholderMax}
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
