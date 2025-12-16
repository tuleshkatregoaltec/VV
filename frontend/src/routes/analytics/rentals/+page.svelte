<script lang="ts">
    import { untrack } from 'svelte';
    import PageHeader from '$lib/components/dashboard/PageHeader.svelte';
    import DashboardCard from '$lib/components/dashboard/DashboardCard.svelte';
    import { analytics, type RentalAnalyticsResponse } from '$lib/api/analytics';
    import { propertyType, timeframe } from '$lib/components/filters/globalFilters.svelte';
    import { TIMEFRAME_MAPPING } from '$lib/constants/transactions';

    let data: RentalAnalyticsResponse | null = $state(null);
    let loading = $state(true);
    let error: string | null = $state(null);

    async function fetchData() {
        loading = true;
        error = null;
        try {
            const timeframeDays = TIMEFRAME_MAPPING[timeframe.current] ?? 30;
            data = await analytics.rentals({ 
                property_usage: propertyType.current, 
                timeframe_days: timeframeDays as 7 | 30 | 90 | 180 | 365
            });
        } catch (e) {
            error = e instanceof Error ? e.message : 'Failed to load analytics';
        } finally {
            loading = false;
        }
    }

    // Fetch when filters change (runs on mount too)
    $effect(() => {
        // Track dependencies
        const _pt = propertyType.current;
        const _tf = timeframe.current;
        // Fetch without tracking the async call
        untrack(() => { fetchData(); });
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
        title="Rental Analytics" 
        subtitle="Market insights and trends for property rentals"
    />

    {#if loading}
        <div class="mt-8 flex justify-center">
            <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
        </div>
    {:else if error}
        <div class="mt-8 bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            {error}
        </div>
    {:else if data}
        <!-- KPI Cards -->
        <div class="mt-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <DashboardCard
                title="Total Annual Value"
                value={formatCurrency(data.summary.total_annual_value)}
                trend={getTrend(data.summary.value_change_pct)}
            />
            <DashboardCard
                title="Contracts"
                value={formatNumber(data.summary.contract_count)}
                trend={getTrend(data.summary.count_change_pct)}
            />
            <DashboardCard
                title="Avg. Annual Rent"
                value={formatCurrency(data.summary.avg_annual_rent)}
            />
            <DashboardCard
                title="Avg. Rent/sq.ft"
                value={formatCurrency(data.summary.avg_rent_sqft)}
            />
        </div>

        <!-- Top Projects -->
        <div class="mt-8 bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-4">Top Projects by Rental Value</h3>
            {#if data.by_master_project.length > 0}
                <div class="overflow-x-auto">
                    <table class="min-w-full divide-y divide-gray-200">
                        <thead>
                            <tr>
                                <th class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Project</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Contracts</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Annual Value</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">Avg/sq.ft</th>
                                <th class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">% of Total</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-gray-200">
                            {#each data.by_master_project as project}
                                <tr class="hover:bg-gray-50">
                                    <td class="px-4 py-3 text-sm font-medium text-gray-900">{project.dimension_value}</td>
                                    <td class="px-4 py-3 text-sm text-gray-600 text-right">{formatNumber(project.contract_count)}</td>
                                    <td class="px-4 py-3 text-sm text-gray-600 text-right">{formatCurrency(project.total_annual_value)}</td>
                                    <td class="px-4 py-3 text-sm text-gray-600 text-right">{formatCurrency(project.avg_rent_sqft)}</td>
                                    <td class="px-4 py-3 text-sm text-gray-600 text-right">{project.pct_of_total?.toFixed(1) ?? '-'}%</td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                </div>
            {:else}
                <p class="text-gray-500 text-center py-4">No data available for this period</p>
            {/if}
        </div>

        <!-- Property Type Breakdown -->
        <div class="mt-8 bg-white rounded-xl shadow-md border border-gray-200 p-6">
            <h3 class="text-lg font-semibold text-gray-900 mb-4">By Property Type</h3>
            {#if data.by_property_type.length > 0}
                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {#each data.by_property_type as item}
                        <div class="bg-gray-50 rounded-lg p-4">
                            <h4 class="font-medium text-gray-900">{item.dimension_value}</h4>
                            <div class="mt-2 space-y-1 text-sm text-gray-600">
                                <p>{formatNumber(item.contract_count)} contracts</p>
                                <p>{formatCurrency(item.total_annual_value)} annual value</p>
                                <p>{formatCurrency(item.avg_rent_sqft)}/sq.ft</p>
                            </div>
                        </div>
                    {/each}
                </div>
            {:else}
                <p class="text-gray-500 text-center py-4">No data available</p>
            {/if}
        </div>
    {/if}
</div>
