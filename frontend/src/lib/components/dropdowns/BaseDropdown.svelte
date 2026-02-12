<script module lang="ts">
  let nextId = 0;
</script>

<script lang="ts">
  import { getContext } from 'svelte';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import type { Snippet } from 'svelte';

  let {
    id = `dropdown-${nextId++}`,
    ariaLabel,
    displayValue,
    align = 'left',
    button,
    children,
    onOpen,
    onClose
  }: {
    id?: string;
    ariaLabel: string;
    displayValue: string;
    align?: 'left' | 'right';
    button?: Snippet<[{ toggle: () => void; isOpen: boolean }]>;
    children: Snippet<[{ close: () => void }]>;
    onOpen?: () => void;
    onClose?: () => void;
  } = $props();

  let localState = $state<string | null>(null);
  let openDropdownIdContext = getContext<{ value: string | null }>('openDropdownId') ?? {
    get value() {
      return localState;
    },
    set value(v: string | null) {
      localState = v;
    }
  };

  let isOpen = $derived(openDropdownIdContext.value === id);

  let wasOpen = $state(false);

  $effect(() => {
    if (isOpen && !wasOpen) {
      onOpen?.();
      wasOpen = true;
    } else if (!isOpen && wasOpen) {
      onClose?.();
      wasOpen = false;
    }
  });

  function toggle() {
    openDropdownIdContext.value = isOpen ? null : id;
  }

  function close() {
    openDropdownIdContext.value = null;
  }

  // Reusable click outside action
  function clickOutside(node: HTMLElement, callback: () => void) {
    function handleClick(event: MouseEvent) {
      if (!node.contains(event.target as Node)) {
        callback();
      }
    }

    document.addEventListener('mousedown', handleClick, true);

    return {
      destroy() {
        document.removeEventListener('mousedown', handleClick, true);
      }
    };
  }
</script>

<div id="dropdown-container-{id}" use:clickOutside={() => { if (isOpen) close(); }}>
  <div class="relative">
    {#if button}
      {@render button({ toggle, isOpen })}
    {:else}
      <button
        id="{id}-button"
        type="button"
        class="w-full px-4 py-2 rounded-lg bg-gray-50 border border-gray-200 text-gray-900 text-left flex items-center justify-between hover:border-gray-300 focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all"
        onclick={toggle}
        aria-label={ariaLabel}
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        <span class:text-gray-400={!displayValue}>{displayValue || 'Select...'}</span>
        <svg
          class="w-4 h-4 text-gray-400 transition-transform duration-200"
          class:rotate-180={isOpen}
          fill="none"
          stroke="currentColor"
          stroke-width="2"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
    {/if}

    {#if isOpen}
      <div
        class="absolute z-50 mt-2 bg-white border border-gray-200 rounded-lg shadow-lg {align === 'right' ? 'right-0' : 'left-0'}"
        style={align === 'right' ? 'min-width: 200px;' : 'width: 100%;'}
        in:fly={{ y: -10, duration: 200, easing: quintOut }}
        out:fade={{ duration: 150 }}
      >
        {@render children({ close })}
      </div>
    {/if}
  </div>
</div>
