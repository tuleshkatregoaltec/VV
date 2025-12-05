<script lang="ts">
    import '../app.css';
    import { QueryClientProvider } from '@tanstack/svelte-query';
    import type { LayoutData } from './$types';
    import type { Snippet } from 'svelte';
    import { onMount } from 'svelte';
    import { page } from '$app/state';
    import { goto } from '$app/navigation';
    import { authStore } from '$lib/stores/auth.svelte';

    let { children, data }: { children: Snippet; data: LayoutData } = $props();
    
    // Prevent concurrent auth checks
    let isCheckingAuth = $state(false);

    const PUBLIC_PATHS = ['/', '/login', '/auth/login', '/auth/callback', '/auth/no-org', '/auth/deactivated'];

    const isPublicPath = $derived(
        page.url.pathname === '/' ||
        PUBLIC_PATHS.slice(1).some((p) => page.url.pathname.startsWith(p))
    );

    onMount(async () => {
        if (!isPublicPath && !isCheckingAuth) {
            isCheckingAuth = true;
            try {
                const authenticated = await authStore.checkAuth();
                if (!authenticated) {
                    goto('/');
                }
            } finally {
                isCheckingAuth = false;
            }
        } else if (isPublicPath) {
            authStore.setLoading(false);
        }
    });
</script>

<svelte:head>
    <link rel="icon" href="/favicon.svg" />
</svelte:head>

<QueryClientProvider client={data.queryClient}>
    {#if !isPublicPath && authStore.loading}
        <div class="flex items-center justify-center min-h-screen bg-gray-50">
            <div class="text-center">
                <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary mb-4"></div>
                <p class="text-gray-600">Loading...</p>
            </div>
        </div>
    {:else if !isPublicPath && !authStore.authenticated}
        <div class="flex items-center justify-center min-h-screen bg-gray-50">
            <p class="text-gray-600">Redirecting...</p>
        </div>
    {:else}
        {@render children()}
    {/if}
</QueryClientProvider>
