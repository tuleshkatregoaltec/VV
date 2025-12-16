<script lang="ts">
    import type { Snippet } from 'svelte';
    import Navbar from '$lib/components/navigation/Navbar.svelte';
    import FilterBar from '$lib/components/filters/FilterBar.svelte';

    import { setContext } from 'svelte';

    let {
        children,
        showFilters = false
    }: {
        children: Snippet;
        showFilters?: boolean;
    } = $props();

    // Shared dropdown open-id context for top-level navigation dropdowns
    let openDropdownId = $state<string | null>(null);
    setContext('openDropdownId', {
        get value() { return openDropdownId; },
        set value(v: string | null) { openDropdownId = v; }
    });
</script>

<div class="h-screen flex flex-col bg-background">
    <Navbar />

    <div class="flex-1 overflow-auto">
        {#if showFilters}
            <FilterBar />
        {/if}
        {@render children()}
    </div>
</div>
