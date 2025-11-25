<script lang="ts">
	import { MAX_VISIBLE_PAGES } from '$lib/constants/transactions';

	let {
		currentPage = $bindable(1),
		totalPages = 1,
		totalRecords = 0,
		itemsPerPage = 50
	}: {
		currentPage?: number;
		totalPages?: number;
		totalRecords?: number;
		itemsPerPage?: number;
	} = $props();

	// Generate page numbers for pagination UI
	const pageNumbers = $derived((() => {
		const pages = [];

		if (totalPages <= MAX_VISIBLE_PAGES) {
			// Show all pages if total is small
			for (let i = 1; i <= totalPages; i++) {
				pages.push(i);
			}
		} else {
			// Show first page, last page, and pages around current
			pages.push(1);

			let start = Math.max(2, currentPage - 2);
			let end = Math.min(totalPages - 1, currentPage + 2);

			if (start > 2) pages.push('...');

			for (let i = start; i <= end; i++) {
				pages.push(i);
			}

			if (end < totalPages - 1) pages.push('...');

			pages.push(totalPages);
		}

		return pages;
	})());

	function goToPage(page: number) {
		if (page >= 1 && page <= totalPages) {
			currentPage = page;
		}
	}

	function nextPage() {
		if (currentPage < totalPages) {
			currentPage++;
		}
	}

	function prevPage() {
		if (currentPage > 1) {
			currentPage--;
		}
	}
</script>

<div class="space-y-4">
	<!-- Results Summary -->
	<div class="flex justify-between items-center">
		<p class="text-sm text-gray-600">
			Showing <span class="font-semibold text-gray-900">{(currentPage - 1) * itemsPerPage + 1}</span>
			to <span class="font-semibold text-gray-900">{Math.min(currentPage * itemsPerPage, totalRecords)}</span> of
			<span class="font-semibold text-gray-900">{totalRecords.toLocaleString()}</span> transactions
		</p>
		<p class="text-sm text-gray-600">
			Page <span class="font-semibold text-gray-900">{currentPage}</span> of <span class="font-semibold text-gray-900">{totalPages}</span>
		</p>
	</div>

	<!-- Pagination Controls -->
	{#if totalPages > 1}
		<div class="flex items-center justify-center gap-2">
			<!-- Previous Button -->
			<button
				onclick={prevPage}
				disabled={currentPage === 1}
				class="px-4 py-2 rounded-lg border font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed {currentPage === 1
					? 'bg-gray-100 text-gray-400 border-gray-300'
					: 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}"
			>
				Previous
			</button>

			<!-- Page Numbers -->
			<div class="flex gap-1">
				{#each pageNumbers as page}
					{#if page === '...'}
						<span class="px-4 py-2 text-gray-500">...</span>
					{:else}
						<button
							onclick={() => goToPage(page)}
							class="px-4 py-2 rounded-lg border font-medium transition-colors {currentPage === page
								? 'bg-primary text-white border-primary'
								: 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}"
						>
							{page}
						</button>
					{/if}
				{/each}
			</div>

			<!-- Next Button -->
			<button
				onclick={nextPage}
				disabled={currentPage === totalPages}
				class="px-4 py-2 rounded-lg border font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed {currentPage ===
				totalPages
					? 'bg-gray-100 text-gray-400 border-gray-300'
					: 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'}"
			>
				Next
			</button>
		</div>
	{/if}
</div>
