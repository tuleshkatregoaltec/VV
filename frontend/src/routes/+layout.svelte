<script lang="ts">
    import '../app.css';
    const favicon = '/favicon.svg';

    import { QueryClientProvider } from '@tanstack/svelte-query';
    import type { LayoutData } from './$types';
    import type { Snippet } from 'svelte';
    import { onMount } from 'svelte';

    import Navbar from '$lib/components/navigation/Navbar.svelte';
    import FilterBar from '$lib/components/filters/FilterBar.svelte';
    import { page } from '$app/state';
    import { goto } from '$app/navigation';
    import { authStore } from '$lib/stores/auth.svelte';

    let { children, data }: { children: Snippet; data: LayoutData } = $props();

    // Public routes (no auth required)
    const PUBLIC_PATHS = ['/', '/login', '/auth/login', '/auth/callback', '/auth/no-org', '/auth/deactivated'];

    // Correct public-path check: '/' exact match, others with startsWith
    const isPublicPath = $derived(
        page.url.pathname === '/' ||
        PUBLIC_PATHS.slice(1).some((p) => page.url.pathname.startsWith(p))
    );

    // Controls whether we are allowed to render the page at all
    let authCheckComplete = $state(false);

    onMount(async () => {
        if (isPublicPath) {
            // Public route: no auth check needed
            authStore.setLoading(false);
            authCheckComplete = true;
            return;
        }

        // Protected route: check auth
        const authenticated = await authStore.checkAuth();
        if (!authenticated) {
            // Redirect to landing, and IMPORTANT: mark this layout as done
            authCheckComplete = true;
            goto('/');
            return;
        }

        // Auth OK, render protected content
        authCheckComplete = true;
    });
</script>

<svelte:head>
    <link rel="icon" href={favicon} />
</svelte:head>

<QueryClientProvider client={data.queryClient}>
    {#if !authCheckComplete}
        <div class="flex items-center justify-center min-h-screen">
            <p class="text-gray-600">Loading...</p>
        </div>
    {:else}
        <div class="h-screen flex flex-col">
            {#if page.url.pathname !== '/' && !isPublicPath}
                <Navbar />
            {/if}
            {#if page.url.pathname !== '/' && !page.error && !isPublicPath}
                <FilterBar />
            {/if}
            <div class="flex-1 flex flex-col {page.error ? 'overflow-hidden' : 'overflow-auto'}">
                {@render children()}
            </div>
        </div>
    {/if}
</QueryClientProvider>
