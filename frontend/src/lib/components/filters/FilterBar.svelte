<script lang="ts">
import StandardDropdown from '../dropdowns/StandardDropdown.svelte'
import FilterToggle from './FilterToggle.svelte'
import { propertyType, timeframe } from './globalFilters.svelte'

const timeframes = ['Last Week', 'Last Month', 'Last 3 Months', 'Last 6 Months', 'Last Year']
</script>

<div class="max-w-7xl mx-auto px-0 sm:px-1 lg:px-1">
	<div class="flex flex-col sm:flex-row items-start sm:items-center gap-4 sm:gap-6 pt-2 sm:pt-4">
		<div class="flex-shrink-0">
			<FilterToggle options={['Residential', 'Commercial']} bind:selected={propertyType.current} />
		</div>

		<div class="flex flex-col sm:flex-row gap-4 ml-auto">
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
