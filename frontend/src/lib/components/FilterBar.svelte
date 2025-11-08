<script lang="ts">
	import FilterToggle from './FilterToggle.svelte';
	import FilterDropdown from './FilterDropdown.svelte';
	import { propertyType, area, timeframe } from './filterStore';

	const areas = ['Dubai Marina', 'Downtown Dubai', 'Jumeirah', 'Business Bay', 'Arabian Ranches'];
	const timeframes = ['Last Week', 'Last Month', 'Last Quarter', 'Last Year'];
</script>

<div
	class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-6 px-4 sm:px-8 pt-2 sm:pt-4 bg-background"
>
	<!-- Toggle -->
	<div class="flex-shrink-0">
		<FilterToggle
			options={['Residential', 'Commercial']}
			bind:selected={$propertyType}
			on:click={() => propertyType.set($propertyType)}
		/>
	</div>

	<!-- Dropdowns -->
	<div class="flex flex-col sm:flex-row gap-4 ml-auto">
		<FilterDropdown
			label="Area"
			options={areas}
			bind:selected={$area}
			on:click={() => area.set($area)}
		/>
		<FilterDropdown
			label="Timeframe"
			options={timeframes}
			bind:selected={$timeframe}
			on:click={() => timeframe.set($timeframe)}
		/>
	</div>
</div>
