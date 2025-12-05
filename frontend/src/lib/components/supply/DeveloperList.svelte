<script lang="ts">
    import { onMount } from 'svelte';
    import { supply, type Developer, type SortOption } from '$lib/api/supply';
    import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte';

    let {
        selectedId = $bindable<number | null>(null),
        selectedDeveloper = $bindable<Developer | null>(null),
        sortBy = $bindable<SortOption>('projects'),
        statusFilter = $bindable<'all' | 'active' | 'completed' | 'cancelled'>('all')
    }: {
        selectedId?: number | null;
        selectedDeveloper?: Developer | null;
        sortBy?: SortOption;
        statusFilter?: 'all' | 'active' | 'completed' | 'cancelled';
    } = $props();

    const PAGE_SIZE = 30;

    let developers: Developer[] = $state([]);
    let totalCount: number = $state(0);
    let loading = $state(true);
    let loadingMore = $state(false);
    let hasMore = $state(true);
    let scrollContainer: HTMLDivElement;

    const sortOptions: { value: SortOption; label: string }[] = [
        { value: 'projects', label: 'Total Projects' },
        { value: 'transactions', label: 'Transactions' },
        { value: 'avg_price', label: 'Avg. Price' }
    ];

    const sortLabels: Record<SortOption, string> = {
        projects: 'Total Projects',
        transactions: 'Transactions',
        avg_price: 'Avg. Price'
    };

    let filteredDevelopers = $derived(
        statusFilter === 'all' 
            ? developers 
            : developers.filter(d => {
                if (statusFilter === 'active') return d.active > 0;
                if (statusFilter === 'completed') return d.completed > 0;
                if (statusFilter === 'cancelled') return d.cancelled > 0;
                return true;
            })
    );

    async function loadInitial() {
        loading = true;
        developers = [];
        hasMore = true;
        
        try {
            const [countRes, devsRes] = await Promise.all([
                supply.getDeveloperCount(),
                supply.getDevelopers(sortBy, PAGE_SIZE, 0)
            ]);
            totalCount = countRes.total;
            developers = devsRes.developers;
            hasMore = developers.length < totalCount;
        } catch (e) {
            console.error('Failed to load developers:', e);
        } finally {
            loading = false;
        }
    }

    async function loadMore() {
        if (loadingMore || !hasMore) return;
        
        loadingMore = true;
        try {
            const res = await supply.getDevelopers(sortBy, PAGE_SIZE, developers.length);
            developers = [...developers, ...res.developers];
            hasMore = developers.length < totalCount;
        } catch (e) {
            console.error('Failed to load more developers:', e);
        } finally {
            loadingMore = false;
        }
    }

    function handleScroll() {
        if (!scrollContainer || loading || loadingMore || !hasMore) return;
        
        const { scrollTop, scrollHeight, clientHeight } = scrollContainer;
        // Load more when within 200px of bottom
        if (scrollHeight - scrollTop - clientHeight < 200) {
            loadMore();
        }
    }

    onMount(() => {
        loadInitial();
    });

    // Reload when sort changes
    let initialized = false;
    $effect(() => {
        const currentSort = sortBy;
        if (initialized) {
            loadInitial();
        }
        initialized = true;
    });

    // Update selectedDeveloper when selection changes
    $effect(() => {
        selectedDeveloper = developers.find(d => d.developer_id === selectedId) ?? null;
    });
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden h-full flex flex-col">
    <div class="px-6 py-4 border-b border-gray-200 bg-gray-50">
        <div class="flex items-center justify-between mb-2">
            <h2 class="text-lg font-semibold text-gray-900">Developers</h2>
            <StandardDropdown
                id="developer-sort"
                ariaLabel="Sort developers by"
                options={sortOptions.map(o => o.label)}
                value={sortLabels[sortBy]}
                onchange={(label) => {
                    const option = sortOptions.find(o => o.label === label);
                    if (option) sortBy = option.value;
                }}
            />
        </div>
        <p class="text-sm text-gray-500">
            {#if loading}
                Loading...
            {:else}
                {filteredDevelopers.length} of {totalCount} developers
            {/if}
        </p>
        
        <!-- Status filter tabs -->
        <div class="flex gap-1 mt-3">
            {#each ['all', 'active', 'completed', 'cancelled'] as filter}
                <button
                    type="button"
                    class="px-3 py-1 text-xs rounded-full transition-colors {statusFilter === filter 
                        ? filter === 'active' ? 'bg-blue-500 text-white' 
                        : filter === 'completed' ? 'bg-green-500 text-white'
                        : filter === 'cancelled' ? 'bg-red-500 text-white'
                        : 'bg-gray-800 text-white'
                        : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
                    onclick={() => statusFilter = filter as typeof statusFilter}
                >
                    {filter === 'all' ? 'All' : filter === 'active' ? 'Active' : filter === 'completed' ? 'Done' : 'Cancelled'}
                </button>
            {/each}
        </div>
    </div>
    
    <div 
        class="flex-1 overflow-y-auto" 
        bind:this={scrollContainer}
        onscroll={handleScroll}
    >
        {#if loading}
            <div class="flex items-center justify-center py-12">
                <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        {:else if filteredDevelopers.length === 0}
            <div class="px-6 py-12 text-center text-gray-500">No developers found</div>
        {:else}
            <ul class="divide-y divide-gray-200">
                {#each filteredDevelopers as dev}
                    <li>
                        <button
                            type="button"
                            class="w-full text-left px-6 py-4 hover:bg-gray-50 transition-colors {selectedId === dev.developer_id ? 'bg-primary/5 border-l-4 border-primary' : ''}"
                            onclick={() => selectedId = dev.developer_id}
                        >
                            <div class="flex items-center justify-between">
                                <span class="font-medium text-gray-900 truncate pr-2">{dev.developer_name}</span>
                                {#if dev.active > 0}
                                    <span class="flex-shrink-0 px-2 py-0.5 text-xs rounded-full bg-blue-100 text-blue-700">
                                        {dev.active} active
                                    </span>
                                {/if}
                            </div>
                            <div class="text-xs text-gray-500 mt-1">
                                {dev.total} projects
                                {#if dev.completed > 0} • {dev.completed} completed{/if}
                                {#if dev.cancelled > 0}<span class="text-red-500"> • {dev.cancelled} cancelled</span>{/if}
                            </div>
                        </button>
                    </li>
                {/each}
            </ul>
            
            {#if loadingMore}
                <div class="flex items-center justify-center py-4">
                    <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-primary"></div>
                </div>
            {:else if hasMore}
                <div class="py-4 text-center text-xs text-gray-400">
                    Scroll for more
                </div>
            {/if}
        {/if}
    </div>
</div>
