<script lang="ts">
    import FilterToggle from './FilterToggle.svelte';
    import SearchableDropdown from '../dropdowns/SearchableDropdown.svelte';
    import StandardDropdown from '../dropdowns/StandardDropdown.svelte';
    import { propertyType, masterProject, timeframe } from './globalFilters.svelte';
    import { filters } from '$lib/api';
    import { onMount } from 'svelte';

    let masterProjects = $state<string[]>(['All']);
    const timeframes = ['Last Week', 'Last Month', 'Last 3 Months', 'Last 6 Months', 'Last Year'];
    
    async function fetchMasterProjects() {
        try {
            const projects = await filters.masterProjects();
            masterProjects = ['All', ...projects];
        } catch (error) {
            console.error('Failed to fetch master projects:', error);
        }
    }

    onMount(() => {
        fetchMasterProjects();
    });
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
                options={masterProjects}
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
