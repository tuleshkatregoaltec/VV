<script lang="ts">
    import type { Snippet } from 'svelte';
    import AppShell from '$lib/components/layout/AppShell.svelte';

    let { children }: { children: Snippet } = $props();
</script>

<AppShell showFilters={true}>
    <div class="min-h-screen bg-slate-50">
        <div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1 py-8">
            {@render children()}
        </div>
    </div>
</AppShell>