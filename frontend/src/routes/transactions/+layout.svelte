<script lang="ts">
    import type { Snippet } from 'svelte';
    import AppShell from '$lib/components/layout/AppShell.svelte';

    let { children }: { children: Snippet } = $props();
</script>

<AppShell showFilters={true}>
    {@render children()}
</AppShell>