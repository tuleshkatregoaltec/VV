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
        rentRange: 'All',
        areaRange: 'All'
    });

    // Filter definitions for FilterPanel
    const RENT_BUCKET_OPTIONS = ['All', '<50K', '50K-100K', '100K-200K', '200K-500K', '500K-1M', '>1M'];
    const AREA_BUCKET_OPTIONS = ['All', '<500', '500-1K', '1K-2K', '2K-3K', '3K-5K', '>5K'];
    const PROPERTY_TYPE_OPTIONS = ['All', 'Unit', 'Villa', 'Building', 'Land'];

    let filterDefinitions = $derived<FilterDefinition[]>([
        {
            id: 'propertyType',
            label: 'Property Type',
            type: 'standard',
            options: PROPERTY_TYPE_OPTIONS
        },
        {
            id: 'rentRange',
            label: 'Rent Range (Annual)',
            type: 'standard',
            options: RENT_BUCKET_OPTIONS
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
            rent_bucket: localFilters.rentRange !== 'All' ? localFilters.rentRange : undefined,
            area_bucket: localFilters.areaRange !== 'All' ? localFilters.areaRange : undefined
        };
    }

    // Analytics query using @tanstack/svelte-query
    const analyticsQuery = createQuery(() => ({
        queryKey: [
            'rental-analytics',
            propertyType.current,
            masterProject.current,
            timeframe.current,
            localFilters.propertyType,
            localFilters.rentRange,
            localFilters.areaRange
        ],
        queryFn: () => analytics.rentals(buildApiParams())
    }));

    function resetLocalFilters() {
        localFilters = {
            propertyType: 'All',
            rentRange: 'All',
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

<div class="min-h-screen bg-slate-50">
    <div class="max-w-7xl mx-auto px-4 py-8">
        <PageHeader
            title="Rental Analytics"
            subtitle="Market insights and trends for property rentals"
        />

        <FilterPanel
            {filterDefinitions}
            bind:filters={localFilters}
            onReset={resetLocalFilters}
        />

        {#if analyticsQuery.isError}
            <div class="bg-red-50 border border-red-200 rounded-lg p-6 text-center mb-6 shadow-sm">
                <p class="text-red-800 font-semibold">Error loading analytics</p>
                <p class="text-red-600 mt-2">{analyticsQuery.error?.message ?? 'Unknown error'}</p>
                <button
                    onclick={() => analyticsQuery.refetch()}
                    class="mt-4 px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition-colors shadow-sm"
                >
                    Retry
                </button>
            </div>
        {/if}

        {#if analyticsQuery.isPending || analyticsQuery.isFetching}
            <div class="flex justify-center py-12">
                <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
            </div>
    {:else if analyticsQuery.data}
        <!-- KPI Cards -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
            <DashboardCard
                title="Total Annual Value"
                value={formatCurrency(analyticsQuery.data.summary.total_annual_value)}
                trend={getTrend(analyticsQuery.data.summary.value_change_pct)}
            />
            <DashboardCard
                title="Contracts"
                value={formatNumber(analyticsQuery.data.summary.contract_count)}
                trend={getTrend(analyticsQuery.data.summary.count_change_pct)}
            />
            <DashboardCard
                title="Avg. Annual Rent"
                value={formatCurrency(analyticsQuery.data.summary.avg_annual_rent)}
            />
            <DashboardCard
                title="Avg. Rent/sq.m"
                value={formatCurrency(analyticsQuery.data.summary.avg_rent_sqft)}
            />
        </div>

        <!-- Trend Chart -->
        <div class="mb-6">
            <TrendChart
                data={analyticsQuery.data.trends}
                title="Rental Trend Over Time"
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

            <!-- By Master Project -->
            <BreakdownChart
                data={analyticsQuery.data.by_master_project}
                title="Top Projects by Rental Value"
                metric="volume"
                height={400}
                maxItems={15}
            />
        </div>
    {/if}
    </div>
</div>
