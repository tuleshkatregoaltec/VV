<script lang="ts">
    import { fly, fade } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';

    type Item = { href: string; label: string };
    
    let {
        label,
        items
    }: {
        label: string;
        items: Item[];
    } = $props();

    let showDropdown = $state(false);
    let timeout: number | undefined;

    const HOVER_DELAY = 150;

    function handleEnter() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            showDropdown = true;
        }, HOVER_DELAY);
    }

    function handleLeave() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            showDropdown = false;
        }, 200);
    }
</script>

<div 
    class="relative"
    role="navigation"
    onmouseenter={handleEnter}
    onmouseleave={handleLeave}
>
    <button
        class="px-3 py-2 text-base font-medium text-gray-700 hover:text-primary rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-1"
        aria-haspopup="true"
        aria-expanded={showDropdown}
    >
        {label}
        <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
    </button>
    
    {#if showDropdown}
        <div 
            class="absolute left-0 mt-1 w-44 bg-white rounded-lg shadow-lg border border-gray-200 py-1"
            in:fly={{ y: -10, duration: 200, easing: quintOut }}
            out:fade={{ duration: 150 }}
        >
            {#each items as item}
                <a
                    href={item.href}
                    class="block px-3 py-2 text-sm text-gray-700 hover:text-primary hover:bg-gray-50 transition-colors"
                >
                    {item.label}
                </a>
            {/each}
        </div>
    {/if}
</div>
