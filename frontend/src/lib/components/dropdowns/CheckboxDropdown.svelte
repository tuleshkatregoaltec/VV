<script lang="ts">
  import BaseDropdown from './BaseDropdown.svelte';

  let {
    id,
    ariaLabel,
    options = [],
    selected = $bindable({})
  }: {
    id: string;
    ariaLabel: string;
    options?: Array<{ id: string; label: string }>;
    selected?: Record<string, boolean>;
  } = $props();

  let selectedCount = $derived(Object.values(selected).filter(Boolean).length);

  function toggleOption(optionId: string) {
    selected = { ...selected, [optionId]: !selected[optionId] };
  }
</script>

<BaseDropdown {id} {ariaLabel} displayValue="" align="right">
  {#snippet button({ toggle, isOpen })}
    <button
      type="button"
      class="p-2 rounded-lg hover:bg-gray-100 border border-gray-200 relative"
      onclick={toggle}
      aria-label={`Toggle options for ${ariaLabel}`}
      aria-haspopup="listbox"
      aria-expanded={isOpen}
    >
      <svg class="w-5 h-5 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
      </svg>
      {#if selectedCount > 0}
        <span
          class="absolute -top-1 -right-1 bg-primary text-white text-xs rounded-full w-5 h-5 flex items-center justify-center font-medium"
        >
          {selectedCount}
        </span>
      {/if}
    </button>
  {/snippet}

  {#snippet children({ close })}
    <div class="p-2" role="listbox" aria-multiselectable="true" tabindex="-1">
      {#each options as option (option.id)}
        <label
          class="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-50 cursor-pointer transition-colors group"
        >
          <div class="relative flex items-center">
            <input
              type="checkbox"
              id="{id}-{option.id}"
              checked={selected[option.id] || false}
              onchange={() => toggleOption(option.id)}
              class="w-4 h-4 text-primary border-gray-300 rounded focus:ring-2 focus:ring-primary/20 cursor-pointer"
              aria-checked={selected[option.id] ? 'true' : 'false'}
              aria-labelledby="{id}-{option.id}-label"
            />
            {#if selected[option.id]}
              <svg
                class="w-3 h-3 text-white absolute left-0.5 pointer-events-none"
                fill="currentColor"
                viewBox="0 0 12 12"
                aria-hidden="true"
              >
                <path d="M10.28 2.28L4.5 8.06 1.72 5.28l.56-.56L4.5 6.94l5.22-5.22.56.56z" />
              </svg>
            {/if}
          </div>
          <span id="{id}-{option.id}-label" class="text-sm text-gray-700 select-none group-hover:text-gray-900">
            {option.label}
          </span>
        </label>
      {/each}
    </div>
  {/snippet}
</BaseDropdown>
