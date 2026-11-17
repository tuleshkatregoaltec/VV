<script lang="ts" generics="T extends object">
import { ChevronDown, RotateCcw, SlidersHorizontal, X } from 'lucide-svelte'
import { onDestroy } from 'svelte'
import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte'
import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte'
import { timeframe } from '$lib/components/filters/globalFilters.svelte'
import type { FilterDefinition } from '$lib/types/filters'
import { searchFilterOptions } from '$lib/utils/filterSearch'

let {
	suggestions = [],
	kind,
	definitions,
	filters = $bindable(),
	loading,
	unavailable,
	onReset
}: {
	suggestions?: string[]
	kind: 'sales' | 'rentals'
	definitions: FilterDefinition[]
	filters: T
	loading: boolean
	unavailable: boolean
	onReset: () => void
} = $props()

const periods = ['Last Week', 'Last Month', 'Last 3 Months', 'Last 6 Months', 'Last Year']
const primaryIds = ['locationSearch', 'selectedPropertyType', 'priceRange', 'rentRange']
let advanced = $derived(definitions.filter((filter) => !primaryIds.includes(filter.id)))
let active = $derived(
	definitions.filter((filter) => valueFor(filter.id) && valueFor(filter.id) !== 'All')
)
let advancedCount = $derived(
	advanced.filter((filter) => valueFor(filter.id) && valueFor(filter.id) !== 'All').length
)

function valueFor(id: string): string {
	return (filters as Record<string, string>)[id] ?? 'All'
}

function change(id: string, value: string) {
	filters = { ...filters, [id]: value }
}
let draft = $state('')
let searchTimer: ReturnType<typeof setTimeout> | undefined
// The input follows the committed search only when that value changes (a reset, a link), not
// whenever another filter changes, which would wipe text typed during the debounce.
const committedSearch = $derived((filters as Record<string, string>).locationSearch ?? '')
$effect(() => {
	draft = committedSearch
})
onDestroy(() => clearTimeout(searchTimer))
function updateSearch(value: string) {
	draft = value
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => change('locationSearch', value.trim()), 350)
}
const searchSuggestions = $derived(searchFilterOptions(suggestions, draft).slice(0, 20))
</script>

<section class="ui-surface relative z-20 p-3 sm:p-4" aria-label="Transaction filters" aria-busy={loading}>
	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" data-testid="primary-filters">
		<div class="min-w-0 space-y-1.5">
			<label for={`${kind}-location-search`} class="text-xs font-medium text-fg-2">Location</label>
			<div class="flex gap-1">
				<input id={`${kind}-location-search`} aria-label="Location keywords" type="search" maxlength="200" list={`${kind}-location-suggestions`} value={draft} oninput={(event) => updateSearch(event.currentTarget.value)} placeholder="Building, project or area" class="ui-field h-10 min-w-0 w-full px-3 text-sm" />
				{#if draft}<button type="button" class="ui-button px-2" aria-label="Clear location search" onclick={() => { clearTimeout(searchTimer); draft = ''; change('locationSearch', '') }}><X size={14} /></button>{/if}
			</div>
			<datalist id={`${kind}-location-suggestions`}>{#each searchSuggestions as suggestion}<option value={suggestion}></option>{/each}</datalist>
		</div>
		{#each definitions.filter((filter) => primaryIds.slice(0, 2).includes(filter.id)) as filter (filter.id)}
			{@render control(filter)}
		{/each}
		<div class="min-w-0 space-y-1.5">
			<label for="transactions-timeframe-button" class="text-xs font-medium text-fg-2">Period</label>
			<StandardDropdown id="transactions-timeframe" ariaLabel="Period" options={periods} bind:value={timeframe.current} />
		</div>
		{#each definitions.filter((filter) => primaryIds.slice(2).includes(filter.id)) as filter (filter.id)}
			{@render control(filter)}
		{/each}
	</div>
	<div class="relative mt-3">
	<details class="group">
		<summary class="ui-button inline-flex h-9 cursor-pointer list-none gap-2 px-3 text-xs [&::-webkit-details-marker]:hidden">
			<SlidersHorizontal size={14} /> More filters
			{#if advancedCount > 0}<span class="ui-selection-badge px-1.5">{advancedCount}</span>{/if}
			<ChevronDown size={14} class="transition-transform group-open:rotate-180" />
		</summary>
		<div class="mt-3 grid grid-cols-1 gap-3 border-t border-border pt-3 sm:grid-cols-2 lg:grid-cols-4">
			{#each advanced as filter (filter.id)}{@render control(filter)}{/each}
		</div>
	</details>
    <button type="button" class="absolute right-0 top-0 inline-flex h-9 items-center gap-1.5 text-xs text-fg-3 hover:text-fg-1" onclick={() => { clearTimeout(searchTimer); draft = ''; onReset() }}>
        <RotateCcw size={13} /> Reset filters
    </button>
    </div>
    {#if active.length > 0}
	<div class="mt-2 flex flex-wrap items-center gap-2">
		{#each active as filter (filter.id)}
			<button type="button" class="ui-button min-h-8 max-w-full gap-1.5 px-2 text-xs" aria-label={`Clear ${filter.label}`} onclick={() => change(filter.id, 'All')}>
				<span class="truncate">{filter.label}: {valueFor(filter.id)}</span><X size={12} class="shrink-0" />
			</button>
		{/each}
	</div>
	{/if}
	{#if loading}<p role="status" class="mt-1 text-xs text-fg-3">Updating filter options…</p>{/if}
</section>

{#snippet control(filter: FilterDefinition)}
	{@const dynamic = filter.id.startsWith('selected')}
	{@const id = `${kind}-filters-${filter.id}-input`}
	<fieldset disabled={dynamic && (loading || unavailable)} class="min-w-0 space-y-1.5 disabled:opacity-60">
		<label for={`${id}-button`} class="text-xs font-medium text-fg-2">{filter.label}</label>
		{#if dynamic}
			<SearchableDropdown {id} ariaLabel={filter.label} options={filter.options ?? []} value={valueFor(filter.id)} onchange={(value) => change(filter.id, value)} approximate />
			{#if !loading && !unavailable && (filter.options?.length ?? 0) <= 1}
				<p class="text-xs text-fg-3">No options for these filters.</p>
			{/if}
		{:else}
			<StandardDropdown {id} ariaLabel={filter.label} options={filter.options ?? []} value={valueFor(filter.id)} onchange={(value) => change(filter.id, value)} />
		{/if}
	</fieldset>
{/snippet}
