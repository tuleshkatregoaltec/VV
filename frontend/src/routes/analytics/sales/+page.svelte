<script lang="ts">
    import { createQuery } from '@tanstack/svelte-query';
    import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
    import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
    import FilterPanel from '$lib/components/filters/FilterPanel.svelte';
    import TrendChart from '$lib/components/charts/TrendChart.svelte';
    import BreakdownChart from '$lib/components/charts/BreakdownChart.svelte';
    import { analytics } from '$lib/api/analytics';
    import { propertyType, masterProject, timeframe } from '$lib/components/filters/globalFilters.svelte';
    import { TIMEFRAME_MAPPING } from '$lib/constants/transactions';
    import type { FilterDefinition } from '$lib/types/filters';

    // Local filter state
    let localFilters = $state({
        propertyType: 'All',
        rooms: 'All',
        regType: 'All',
        priceRange: 'All',
        areaRange: 'All'
    });

    // Filter definitions for FilterPanel
    const PRICE_BUCKET_OPTIONS = ['All', '<500K', '500K-1M', '1M-2M', '2M-5M', '5M-10M', '10M-25M', '>25M'];
    const AREA_BUCKET_OPTIONS = ['All', '<500', '500-1K', '1K-2K', '2K-3K', '3K-5K', '>5K'];
    const PROPERTY_TYPE_OPTIONS = ['All', 'Unit', 'Villa', 'Building', 'Land'];
    const ROOMS_OPTIONS = ['All', 'Studio', '1 B/R', '2 B/R', '3 B/R', '4 B/R', '5 B/R', '6 B/R+'];
    const REG_TYPE_OPTIONS = ['All', 'Ready', 'Offplan'];

    let filterDefinitions = $derived<FilterDefinition[]>([
        {
            id: 'propertyType',
            label: 'Property Type',
            type: 'standard',
            options: PROPERTY_TYPE_OPTIONS
        },
        {
            id: 'rooms',
            label: 'Rooms',
            type: 'standard',
            options: ROOMS_OPTIONS
        },
        {
            id: 'regType',
            label: 'Registration',
            type: 'standard',
            options: REG_TYPE_OPTIONS
        },
        {
            id: 'priceRange',
            label: 'Price Range',
            type: 'standard',
            options: PRICE_BUCKET_OPTIONS
        },
        {
            id: 'areaRange',
            label: 'Area (sq.m)',
            type: 'standard',
            options: AREA_BUCKET_OPTIONS
        }
    ]);

    // Build API parameters from filters
    function buildApiParams() {
        return {
            property_usage: propertyType.current,
            timeframe_days: TIMEFRAME_MAPPING[timeframe.current] ?? 30,
            master_project: masterProject.current !== 'All' ? masterProject.current : undefined,
            property_type: localFilters.propertyType !== 'All' ? localFilters.propertyType : undefined,
            rooms: localFilters.rooms !== 'All' ? localFilters.rooms : undefined,
            reg_type: localFilters.regType !== 'All' ? localFilters.regType : undefined,
            price_bucket: localFilters.priceRange !== 'All' ? localFilters.priceRange : undefined,
            area_bucket: localFilters.areaRange !== 'All' ? localFilters.areaRange : undefined
        };
    }

    // Analytics query using @tanstack/svelte-query
    const analyticsQuery = createQuery(() => ({
        queryKey: [
            'sales-analytics',
            propertyType.current,
            masterProject.current,
            timeframe.current,
            localFilters.propertyType,
            localFilters.rooms,
            localFilters.regType,
            localFilters.priceRange,
            localFilters.areaRange
        ],
        queryFn: () => analytics.sales(buildApiParams())
    }));

    function resetLocalFilters() {
        localFilters = {
            propertyType: 'All',
            rooms: 'All',
            regType: 'All',
            priceRange: 'All',
            areaRange: 'All'
        };
    }

    // Reset local filters when global filters change
    $effect(() => {
        const _ = [propertyType.current, masterProject.current, timeframe.current];
        resetLocalFilters();
    });

    function formatCurrency(value: number): string {
        if (value >= 1_000_000_000) return `AED ${(value / 1_000_000_000).toFixed(1)}B`;
        if (value >= 1_000_000) return `AED ${(value / 1_000_000).toFixed(1)}M`;
        if (value >= 1_000) return `AED ${(value / 1_000).toFixed(0)}K`;
        return `AED ${value.toFixed(0)}`;
    }

    function formatNumber(value: number): string {
        return value.toLocaleString();
    }

    function getTrend(pct: number | null): { value: string; direction: 'up' | 'down' } | null {
        if (pct === null) return null;
        return {
            value: `${Math.abs(pct).toFixed(1)}% vs prev period`,
            direction: pct >= 0 ? 'up' : 'down'
        };
    }
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
    <PageHeader
        title="Sales Analytics"
        subtitle="Market insights and trends for property sales"
    />

    <FilterPanel
        {filterDefinitions}
        bind:filters={localFilters}
        onReset={resetLocalFilters}
    />

    {#if analyticsQuery.isError}
        <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6">
            <p class="text-red-800 font-semibold">Error loading analytics</p>
            <p class="text-red-600 mt-2">{analyticsQuery.error?.message ?? 'Unknown error'}</p>
            <button
                onclick={() => analyticsQuery.refetch()}
                class="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
            >
                Retry
            </button>
        </div>
    {/if}

    {#if analyticsQuery.isPending || analyticsQuery.isFetching}
        <div class="flex justify-center py-12">
            <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
        </div>
    {:else if analyticsQuery.data}
        <!-- KPI Cards -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
            <DashboardCard
                title="Total Volume"
                value={formatCurrency(analyticsQuery.data.summary.total_volume)}
                trend={getTrend(analyticsQuery.data.summary.volume_change_pct)}
            />
            <DashboardCard
                title="Transactions"
                value={formatNumber(analyticsQuery.data.summary.transaction_count)}
                trend={getTrend(analyticsQuery.data.summary.count_change_pct)}
            />
            <DashboardCard
                title="Avg. Price"
                value={formatCurrency(analyticsQuery.data.summary.avg_price)}
            />
            <DashboardCard
                title="Avg. Price/sq.m"
                value={formatCurrency(analyticsQuery.data.summary.avg_price_sqft)}
            />
        </div>

        <!-- Trend Chart -->
        <div class="mb-6">
            <TrendChart
                data={analyticsQuery.data.trends}
                title="Sales Trend Over Time"
                metric="volume"
                height={350}
            />
        </div>

        <!-- Charts Grid -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- By Property Type -->
            <BreakdownChart
                data={analyticsQuery.data.by_property_type}
                title="By Property Type"
                metric="volume"
                height={400}
                maxItems={10}
            />

            <!-- By Rooms -->
            <BreakdownChart
                data={analyticsQuery.data.by_rooms}
                title="By Rooms"
                metric="volume"
                height={400}
                maxItems={10}
            />

            <!-- By Registration Type -->
            <BreakdownChart
                data={analyticsQuery.data.by_reg_type}
                title="By Registration Type"
                metric="volume"
                height={300}
                maxItems={5}
            />

            <!-- By Master Project -->
            <BreakdownChart
                data={analyticsQuery.data.by_master_project}
                title="Top Projects by Volume"
                metric="volume"
                height={400}
                maxItems={15}
            />
        </div>
    {/if}
</div>
