<script lang="ts">
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

  function select(option: string, close: () => void) {
    value = option;
    onchange?.(option);
    close();
  }
</script>

<BaseDropdown {id} {ariaLabel} displayValue={value}>
  {#snippet children({ close })}
    <ul class="max-h-60 overflow-y-auto p-2">
      {#each options as option}
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
    </ul>
  {/snippet}
</BaseDropdown>
