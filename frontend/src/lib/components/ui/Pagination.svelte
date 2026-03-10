<script lang="ts">
let {
	currentPage = $bindable(1),
	totalPages,
	totalItems,
	itemsPerPage,
	itemLabel = 'results'
}: {
	currentPage?: number
	totalPages: number
	totalItems: number
	itemsPerPage: number
	itemLabel?: string
} = $props()

let startItem = $derived(totalItems === 0 ? 0 : (currentPage - 1) * itemsPerPage + 1)
let endItem = $derived(Math.min(currentPage * itemsPerPage, totalItems))

let canGoPrev = $derived(currentPage > 1)
let canGoNext = $derived(currentPage < totalPages)

function prev() {
	if (canGoPrev) currentPage--
}

function next() {
	if (canGoNext) currentPage++
}
</script>

{#if totalItems > 0}
	<nav class="flex items-center justify-between" aria-label="Pagination">
		<p class="text-sm text-gray-600">
			<span class="font-medium">{startItem.toLocaleString()}</span>–<span class="font-medium"
				>{endItem.toLocaleString()}</span
			>
			of <span class="font-medium">{totalItems.toLocaleString()}</span>
			{itemLabel}
		</p>

		{#if totalPages > 1}
			<div class="flex items-center gap-0.5">
				<button
					type="button"
					onclick={() => (currentPage = 1)}
					disabled={!canGoPrev}
					class="p-1.5 rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none"
					aria-label="First page"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M11 17l-5-5 5-5M17 17l-5-5 5-5"
						/>
					</svg>
				</button>

				<button
					type="button"
					onclick={prev}
					disabled={!canGoPrev}
					class="p-1.5 rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none"
					aria-label="Previous page"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
					</svg>
				</button>

				<span class="px-2 text-sm text-gray-500 tabular-nums">
					{currentPage}/{totalPages}
				</span>

				<button
					type="button"
					onclick={next}
					disabled={!canGoNext}
					class="p-1.5 rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none"
					aria-label="Next page"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
					</svg>
				</button>

				<button
					type="button"
					onclick={() => (currentPage = totalPages)}
					disabled={!canGoNext}
					class="p-1.5 rounded text-gray-400 hover:text-gray-600 disabled:opacity-30 disabled:pointer-events-none"
					aria-label="Last page"
				>
					<svg
						class="w-4 h-4"
						fill="none"
						stroke="currentColor"
						stroke-width="2.5"
						viewBox="0 0 24 24"
					>
						<path stroke-linecap="round" stroke-linejoin="round" d="M13 7l5 5-5 5M7 7l5 5-5 5" />
					</svg>
				</button>
			</div>
		{/if}
	</nav>
{/if}
