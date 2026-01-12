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
    <meta name="author" content="Vitevue" />
    <meta name="theme-color" content="#000000" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Vitevue" />
    <meta name="twitter:card" content="summary_large_image" />
</svelte:head>

<QueryClientProvider client={data.queryClient}>
    {@render children()}
</QueryClientProvider>
