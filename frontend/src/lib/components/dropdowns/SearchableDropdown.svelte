<script lang="ts">
  import { onDestroy } from 'svelte';
  import BaseDropdown from './BaseDropdown.svelte';

  let {
    id,
    ariaLabel,
    options,
    value = $bindable('All'),
    onchange
  }: {
    id: string;
    ariaLabel: string;
    options: string[];
    value?: string;
    onchange?: (newValue: string) => void;
  } = $props();

  let searchQuery = $state('');
  let visibleCount = $state(50); // Start with 50 items
  let loadingHandle: number | null = null;

  // Cleanup on component destroy to prevent memory leaks
  onDestroy(() => {
    if (loadingHandle) {
      cancelIdleCallback(loadingHandle);
      loadingHandle = null;
    }
  });

  function onOpen() {
    visibleCount = 50;

    if (loadingHandle) {
      cancelIdleCallback(loadingHandle);
    }

    const loadMore = () => {
      if (visibleCount < options.length) {
        visibleCount = Math.min(visibleCount + 100, options.length);

        if (visibleCount < options.length) {
          loadingHandle = requestIdleCallback(loadMore);
        }
      }
    };

    loadingHandle = requestIdleCallback(loadMore);
  }

  function onClose() {
    if (loadingHandle) {
      cancelIdleCallback(loadingHandle);
      loadingHandle = null;
    }
    searchQuery = '';
    visibleCount = 50;
  }

  function select(option: string, close: () => void) {
    value = option;
    onchange?.(option);
    close();
  }

  let filteredOptions = $derived(
    options.filter((option) => option.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  let displayedOptions = $derived(filteredOptions.slice(0, visibleCount));
</script>

<BaseDropdown {id} {ariaLabel} displayValue={value} onOpen={onOpen} onClose={onClose}>
  {#snippet children({ close })}
    <div class="p-2">
      <input
        type="text"
        class="w-full px-3 py-2 mb-2 rounded bg-gray-50 border border-gray-200 text-gray-900 placeholder-gray-400 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
        placeholder="Search..."
        bind:value={searchQuery}
        aria-label={`Search options for ${ariaLabel}`}
      />
      <ul class="max-h-80 overflow-y-auto">
        {#each displayedOptions as option}
          <li>
            <button
              type="button"
              class="w-full text-left px-3 py-2 rounded hover:bg-gray-100 transition-colors {option === value ? 'bg-primary/10 font-semibold text-primary' : 'text-gray-900'}"
              onclick={() => select(option, close)}
            >
              {option}
            </button>
          </li>
        {/each}
        {#if filteredOptions.length === 0}
          <li class="px-3 py-2 text-gray-400 text-sm">No results found</li>
        {/if}
      </ul>
    </div>
  {/snippet}
</BaseDropdown>
