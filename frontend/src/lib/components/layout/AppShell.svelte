<script lang="ts">
    import type { Snippet } from 'svelte';
    import Navbar from '$lib/components/navigation/Navbar.svelte';
    import FilterBar from '$lib/components/filters/FilterBar.svelte';

    let {
        children,
        showFilters = false
    }: {
        children: Snippet;
        showFilters?: boolean;
    } = $props();
</script>

<div class="h-screen flex flex-col bg-background">
    <Navbar />
    {#if showFilters}
        <FilterBar />
    {/if}
    <div class="flex-1 overflow-auto">
        {@render children()}
    </div>
</div>
