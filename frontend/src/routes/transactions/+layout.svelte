<script lang="ts">
    import type { Snippet } from 'svelte';
    import AppShell from '$lib/components/layout/AppShell.svelte';
    import { setContext } from 'svelte';

    let { children }: { children: Snippet } = $props();

    // Shared dropdown open-id context for transactions pages
    let openDropdownId = $state<string | null>(null);
    setContext('openDropdownId', {
        get value() { return openDropdownId; },
        set value(v: string | null) { openDropdownId = v; }
    });
</script>

<AppShell showFilters={true}>
    <div class="min-h-screen bg-background">
        <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
            {@render children()}
        </div>
    </div>
</AppShell>