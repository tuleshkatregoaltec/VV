<script lang="ts">
import CheckboxDropdown from '$lib/components/dropdowns/CheckboxDropdown.svelte'
import SearchableDropdown from '$lib/components/dropdowns/SearchableDropdown.svelte'
import StandardDropdown from '$lib/components/dropdowns/StandardDropdown.svelte'
import type { FilterDefinition } from '$lib/types/filters'

let {
	filterDefinitions = [],
	filters = $bindable({}),
	onReset = () => {},
	onExport = () => {},
	selectedCount = 0,
	onClearSelection = () => {}
}: {
	filterDefinitions?: FilterDefinition[]
	filters?: Record<string, any>
	onReset?: () => void
	onExport?: () => void
	selectedCount?: number
	onClearSelection?: () => void
} = $props()

function resetFilters() {
	filters = {}
	onReset()
}

// Helper to get filter value with fallback
function getFilterValue(id: string): string {
	return filters[id] ?? 'All'
}

// Helper to update filter value (supports both string and checkbox object values)
function setFilterValue(id: string, value: any) {
	filters = { ...filters, [id]: value }
}
</script>

<div
	class="relative z-10 mb-6 rounded-lg border border-[var(--color-border)] bg-white p-4 sm:p-5"
>
	<div class="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
		<div class="flex flex-wrap items-center gap-3">
			<h2 class="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--color-fg-4)]">Filters</h2>
			{#if selectedCount > 0}
				<div
					class="flex items-center gap-2 rounded-sm border border-[var(--color-navy-100)] bg-[var(--color-navy-50)] px-2.5 py-1 text-xs font-medium text-[var(--color-navy-900)]"
				>
					<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
					<span>{selectedCount} selected</span>
					<button
						onclick={onClearSelection}
						class="ml-1 transition-colors hover:text-[var(--color-fg-1)]"
						aria-label="Clear selection"
					>
						<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							/>
						</svg>
					</button>
				</div>
			{/if}
		</div>
		<div class="flex items-center gap-2">
			<button
				onclick={resetFilters}
				class="rounded-md border border-[var(--color-border)] px-3 py-2 text-sm font-medium text-[var(--color-fg-2)] transition-colors hover:border-[var(--color-border-strong)] hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			>
				Reset
			</button>

			<button
				onclick={onExport}
				class="inline-flex items-center gap-2 rounded-md border border-[var(--color-navy-900)] bg-[var(--color-navy-900)] px-3 py-2 text-sm font-medium text-[var(--color-fg-on-navy)] transition-colors hover:bg-[var(--color-navy-800)]"
			>
				<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
					/>
				</svg>
				Export {selectedCount > 0 ? '(' + selectedCount + ')' : '(100 max)'}
			</button>
		</div>
	</div>

	<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
		{#each filterDefinitions as filter (filter.id)}
			<div class="flex flex-col gap-2">
				<!-- Reverted back to <label> tag -->
				<label for="{filter.id}-input" class="block text-sm font-medium text-[var(--color-fg-1)]">
					{filter.label}
				</label>

				{#if filter.type === 'searchable'}
					<SearchableDropdown
						id="{filter.id}-input"
						ariaLabel={filter.label}
						options={filter.options || []}
						value={getFilterValue(filter.id)}
						onchange={(v) => setFilterValue(filter.id, v)}
					/>
				{:else if filter.type === 'standard'}
					<StandardDropdown
						id="{filter.id}-input"
						ariaLabel={filter.label}
						options={filter.options || []}
						value={getFilterValue(filter.id)}
						onchange={(v) => setFilterValue(filter.id, v)}
					/>
				{:else if filter.type === 'checkbox'}
					<CheckboxDropdown
						id="{filter.id}-input"
						ariaLabel={filter.label}
						options={(filter.options || []).map((o) => ({ id: o, label: o }))}
						selected={filters[filter.id] ?? {}}
						onchange={(selected) => setFilterValue(filter.id, selected)}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
