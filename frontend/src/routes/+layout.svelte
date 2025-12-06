<script lang="ts">
    import '../app.css';
    import { QueryClientProvider } from '@tanstack/svelte-query';
    import type { LayoutData } from './$types';
    import type { Snippet } from 'svelte';
    import { authStore } from '$lib/stores/auth.svelte';

    let { children, data }: { children: Snippet; data: LayoutData } = $props();

    // Sync user from load function to authStore reactively
    $effect(() => {
        if (data.user) {
            authStore.setUser(data.user);
        } else {
            authStore.setLoading(false);
        }
    });
</script>

<svelte:head>
    <link rel="icon" href="/favicon.svg" />
</svelte:head>

<QueryClientProvider client={data.queryClient}>
    {@render children()}
</QueryClientProvider>
