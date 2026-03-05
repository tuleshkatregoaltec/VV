<script lang="ts">
    import type { Snippet } from 'svelte';
    import AppShell from '$lib/components/layout/AppShell.svelte';
    import { page } from '$app/state';

    let { children }: { children: Snippet } = $props();

    const navItems = [
        { href: '/admin/organizations', label: 'Organizations' },
    ];
</script>

<AppShell showFilters={false}>
    <div class="max-w-7xl mx-auto px-4 pt-6 pb-2">
        <div class="flex items-center gap-2 mb-1">
            <span class="text-xs font-semibold uppercase tracking-widest text-gray-400">Admin</span>
        </div>
        <nav class="flex gap-1 border-b border-gray-200">
            {#each navItems as item}
                <a
                    href={item.href}
                    class="px-4 py-2 text-sm font-medium rounded-t transition-colors
                        {page.url.pathname.startsWith(item.href)
                            ? 'border-b-2 border-blue-600 text-blue-600'
                            : 'text-gray-500 hover:text-gray-800'}"
                >
                    {item.label}
                </a>
            {/each}
        </nav>
    </div>
    {@render children()}
</AppShell>
