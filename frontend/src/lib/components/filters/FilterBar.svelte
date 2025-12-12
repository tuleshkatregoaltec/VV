<script lang="ts">
    import FilterToggle from './FilterToggle.svelte';
    import SearchableDropdown from '../dropdowns/SearchableDropdown.svelte';
    import StandardDropdown from '../dropdowns/StandardDropdown.svelte';
    import { propertyType, masterProject, timeframe } from './globalFilters.svelte';
    import { filters } from '$lib/api';
    import { createQuery } from '@tanstack/svelte-query';

    // Use TanStack Query to fetch and cache master projects
    const masterProjectsQuery = createQuery(() => ({
        queryKey: ['master-projects'],
        queryFn: () => filters.masterProjects(),
        staleTime: 24 * 60 * 60 * 1000, // 24 hours
    }));
    const timeframes = ['Last Week', 'Last Month', 'Last 3 Months', 'Last 6 Months', 'Last Year'];
    
    // masterProjects are read from the query's data in the template
</script>

<div
    class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-6 px-4 sm:px-8 pt-2 sm:pt-4 bg-background"
>
    <div class="flex-shrink-0">
        <FilterToggle
            options={['Residential', 'Commercial']}
            bind:selected={propertyType.current}
        />
    </div>

    <div class="flex flex-col sm:flex-row gap-4 ml-auto">
        <div class="w-48">
            <SearchableDropdown
                id="filterbar-master-project"
                ariaLabel="Master Project"
                options={['All', ...(masterProjectsQuery.data ?? [])]}
                bind:value={masterProject.current}
            />
        </div>
        <div class="w-48">
            <StandardDropdown
                id="filterbar-timeframe"
                ariaLabel="Timeframe"
                options={timeframes}
                bind:value={timeframe.current}
            />
        </div>
    </div>
</div>
