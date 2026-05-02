<script lang="ts">
import { onDestroy } from 'svelte'
import BaseDropdown from './BaseDropdown.svelte'

let {
	id,
	ariaLabel,
	options,
	value = $bindable('All'),
	onchange
}: {
	id: string
	ariaLabel: string
	options: string[]
	value?: string
	onchange?: (newValue: string) => void
} = $props()

let searchQuery = $state('')
let visibleCount = $state(50) // Start with 50 items
let loadingHandle: number | null = null

// Cleanup on component destroy to prevent memory leaks
onDestroy(() => {
	if (loadingHandle) {
		cancelIdleCallback(loadingHandle)
		loadingHandle = null
	}
})

function onOpen() {
	visibleCount = 50

	if (loadingHandle) {
		cancelIdleCallback(loadingHandle)
	}

	const loadMore = () => {
		if (visibleCount < options.length) {
			visibleCount = Math.min(visibleCount + 100, options.length)

			if (visibleCount < options.length) {
				loadingHandle = requestIdleCallback(loadMore)
			}
		}
	}

	loadingHandle = requestIdleCallback(loadMore)
}

function onClose() {
	if (loadingHandle) {
		cancelIdleCallback(loadingHandle)
		loadingHandle = null
	}
	searchQuery = ''
	visibleCount = 50
}

function select(option: string, close: () => void) {
	value = option
	onchange?.(option)
	close()
}

let filteredOptions = $derived(
	options.filter((option) => option.toLowerCase().includes(searchQuery.toLowerCase()))
)

let displayedOptions = $derived(filteredOptions.slice(0, visibleCount))
</script>

<BaseDropdown {id} {ariaLabel} displayValue={value} {onOpen} {onClose}>
	{#snippet children({ close })}
		<div class="p-1.5">
			<input
				type="text"
				class="mb-2 w-full rounded-md border border-[var(--color-border)] bg-slate-50 px-3 py-2 text-sm text-[var(--color-fg-1)] placeholder-[var(--color-fg-5)] transition-all focus:border-[var(--color-navy-900)] focus:outline-none focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
				placeholder="Search..."
				bind:value={searchQuery}
				aria-label={`Search options for ${ariaLabel}`}
			/>
			<ul class="max-h-80 overflow-y-auto">
				{#each displayedOptions as option (option)}
					<li>
						<button
							type="button"
							class="w-full rounded-md px-3 py-2 text-left text-sm transition-colors {option ===
							value
								? 'bg-[var(--color-navy-50)] font-medium text-[var(--color-navy-900)]'
								: 'text-[var(--color-fg-2)] hover:bg-slate-50 hover:text-[var(--color-fg-1)]'}"
							onclick={() => select(option, close)}
						>
							{option}
						</button>
					</li>
				{/each}
				{#if filteredOptions.length === 0}
					<li class="px-3 py-2 text-sm text-[var(--color-fg-5)]">No results found</li>
				{/if}
			</ul>
		</div>
	{/snippet}
</BaseDropdown>
