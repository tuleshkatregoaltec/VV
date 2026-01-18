<script lang="ts">
	import ColumnSettingsDropdown from '$lib/components/dropdowns/ColumnSettingsDropdown.svelte';

	let {
		columns = [],
		data = [],
		emptyMessage = 'No data available',
		loading = false,
		onrowclick,
		// Selection props
		selectable = false,
		selectedIds = $bindable(new Set<string>()),
		getRowId
	}: {
		columns?: Array<{
			id: string;
			label: string;
			align?: 'left' | 'center' | 'right';
			format?: (value: any, row: any) => string;
			badge?: boolean;
			highlighted?: boolean;
			defaultVisible?: boolean;
		}>;
		data?: Array<Record<string, any>>;
		emptyMessage?: string;
		loading?: boolean;
		onrowclick?: (row: any) => void;
		// Selection
		selectable?: boolean;
		selectedIds?: Set<string>;
		getRowId?: (row: any) => string;
	} = $props();

	// Track which columns are visible (using column id as key)
	let columnVisibility: Record<string, boolean> = $state({});
	let hoveredRowId: string | null = $state(null);
	let lastColumnsKey = '';

	// Initialize column visibility from defaultVisible property when columns change
	$effect(() => {
		// Create a key based on column IDs to detect when columns have changed
		const columnsKey = columns.map(c => c.id).join(',');
		
		if (columnsKey !== lastColumnsKey) {
			// Columns have changed - reinitialize visibility
			const newVisibility: Record<string, boolean> = {};
			for (const col of columns) {
				// Preserve existing visibility preference if column still exists
				if (col.id in columnVisibility) {
					newVisibility[col.id] = columnVisibility[col.id];
				} else {
					newVisibility[col.id] = col.defaultVisible !== false;
				}
			}
			columnVisibility = newVisibility;
			lastColumnsKey = columnsKey;
		}
	});

	// All columns are available for toggling
	let allColumnOptions = $derived(
		columns.map((c) => ({ id: c.id, label: c.label }))
	);

	let visibleColumns = $derived(columns.filter((c) => columnVisibility[c.id]));

	// Selection mode is active when any items are selected
	let inSelectionMode = $derived(selectable && selectedIds.size > 0);

	// Get all row IDs on current page
	let allRowIds = $derived(data.map(row => getRowId?.(row) ?? row.id));

	// Check if all rows on current page are selected
	let allSelected = $derived(
		selectable && data.length > 0 &&
		allRowIds.every(id => selectedIds.has(id))
	);

	// Check if some (but not all) rows on current page are selected
	let someSelected = $derived(
		selectable &&
		allRowIds.some(id => selectedIds.has(id)) &&
		!allSelected
	);

	function handleRowClick(row: any) {
		onrowclick?.(row);
	}

	function toggleSelectAll() {
		const newSet = new Set(selectedIds);
		if (allSelected) {
			// Deselect all on current page
			allRowIds.forEach(id => newSet.delete(id));
		} else {
			// Select all on current page
			allRowIds.forEach(id => newSet.add(id));
		}
		selectedIds = newSet;
	}

	function toggleRow(row: any, event: Event) {
		event.stopPropagation(); // Prevent row click handler
		const id = getRowId?.(row) ?? row.id;
		const newSet = new Set(selectedIds);
		if (newSet.has(id)) {
			newSet.delete(id);
		} else {
			newSet.add(id);
		}
		selectedIds = newSet;
	}

	function isRowSelected(row: any): boolean {
		const id = getRowId?.(row) ?? row.id;
		return selectedIds.has(id);
	}

	function showCheckbox(row: any): boolean {
		if (!selectable) return false;
		// Always show in selection mode, or when hovering this row
		const id = getRowId?.(row) ?? row.id;
		return inSelectionMode || hoveredRowId === id;
	}
</script>

<div class="bg-white/80 backdrop-blur-sm rounded-xl shadow-sm border border-slate-200 overflow-hidden">
  <!-- Column settings dropdown in upper right -->
  <div class="flex items-center justify-end px-4 py-2 bg-slate-50 border-b border-slate-200">
    <ColumnSettingsDropdown
      id="column-visibility"
      ariaLabel="Column Settings"
      options={allColumnOptions}
      bind:selected={columnVisibility}
    />
  </div>

  <div class="overflow-x-auto">
    <table class="w-full">
      <thead class="bg-slate-50 border-b border-slate-200">
        <tr>
          {#if selectable}
            <th class="px-6 py-3 w-12">
              {#if inSelectionMode}
                <input
                  type="checkbox"
                  checked={allSelected}
                  indeterminate={someSelected}
                  onchange={toggleSelectAll}
                  class="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary cursor-pointer"
                  aria-label="Select all transactions on this page"
                />
              {/if}
            </th>
          {/if}
          {#each visibleColumns as column}
            <th
              class="px-6 py-3 text-{column.align || 'left'} text-xs font-medium text-slate-600 uppercase tracking-wider whitespace-nowrap"
            >
              {column.label}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-200">
        {#if loading}
          <tr>
            <td colspan={visibleColumns.length + (selectable ? 1 : 0)} class="px-6 py-16 text-center">
              <div class="flex flex-col items-center gap-3">
                <div class="inline-block animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
                <span class="text-slate-500 text-sm">Loading...</span>
              </div>
            </td>
          </tr>
        {:else if data.length === 0}
          <tr>
            <td colspan={visibleColumns.length + (selectable ? 1 : 0)} class="px-6 py-12 text-center text-slate-500">
              {emptyMessage}
            </td>
          </tr>
		{:else}
			{#each data as row}
				<tr
					onmouseenter={() => { if (selectable) hoveredRowId = getRowId?.(row) ?? row.id; }}
					onmouseleave={() => { if (selectable) hoveredRowId = null; }}
					onclick={() => handleRowClick(row)}
					class="hover:bg-slate-50 transition-colors cursor-pointer {isRowSelected(row) ? 'bg-primary/5' : ''}"
				>
					{#if selectable}
						<td class="px-6 py-4 w-12">
							<div
								class="flex items-center justify-center transition-opacity duration-150 {showCheckbox(row) ? 'opacity-100' : 'opacity-0'}"
							>
								<input
									type="checkbox"
									checked={isRowSelected(row)}
									onchange={(e) => toggleRow(row, e)}
									onclick={(e) => e.stopPropagation()}
									class="w-4 h-4 text-primary border-slate-300 rounded focus:ring-primary cursor-pointer"
									aria-label="Select transaction"
								/>
							</div>
						</td>
					{/if}
					{#each visibleColumns as column}
						<td
							class="px-6 py-4 whitespace-nowrap text-{column.align || 'left'} text-sm {column.highlighted
								? 'text-primary font-semibold'
								: 'text-gray-900'}"
						>
							{#if column.badge}
								<span
									class="px-3 py-1 rounded-full bg-gray-100 text-gray-700 text-xs font-medium"
								>
									{column.format ? column.format(row[column.id], row) : row[column.id]}
								</span>
							{:else}
								{column.format ? column.format(row[column.id], row) : row[column.id]}
							{/if}
						</td>
					{/each}
				</tr>
			{/each}
		{/if}
      </tbody>
    </table>
  </div>
</div>
