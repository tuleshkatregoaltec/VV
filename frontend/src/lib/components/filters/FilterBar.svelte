<script lang="ts">
    import FilterToggle from './FilterToggle.svelte';
    import SearchableDropdown from '../dropdowns/SearchableDropdown.svelte';
    import StandardDropdown from '../dropdowns/StandardDropdown.svelte';
    import { propertyType, masterProject, timeframe } from './globalFilters.svelte';
    import { filters } from '$lib/api/filters';
    import { createQuery } from '@tanstack/svelte-query';

    const masterProjectsQuery = createQuery(() => ({
        queryKey: ['master-projects'],
        queryFn: () => filters.masterProjects(),
        staleTime: 24 * 60 * 60 * 1000,
    }));
    
    const timeframes = ['Last Week', 'Last Month', 'Last 3 Months', 'Last 6 Months', 'Last Year'];
</script>

<div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1">
    <div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-6 pt-2 sm:pt-4">
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
</div>
