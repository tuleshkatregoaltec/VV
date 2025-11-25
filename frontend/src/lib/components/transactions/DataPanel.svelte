<script lang="ts">
	import CheckboxDropdown from '$lib/components/dropdowns/CheckboxDropdown.svelte';

	let {
		columns = [],
		data = [],
		emptyMessage = 'No data available',
		onrowclick
	}: {
		columns?: Array<{
			id: string;
			label: string;
			align?: 'left' | 'center' | 'right';
			format?: (value: any, row: any) => string;
			badge?: boolean;
			highlighted?: boolean;
			optional?: boolean;
		}>;
		data?: Array<Record<string, any>>;
		emptyMessage?: string;
		onrowclick?: (row: any) => void;
	} = $props();

	// Track which optional columns are shown
	let shownOptional: Record<string, boolean> = $state({});

	let optionalColumns = $derived(
		columns.filter((c) => c.optional).map((c) => ({ id: c.id, label: c.label }))
	);

	let visibleColumns = $derived(columns.filter((c) => !c.optional || shownOptional[c.id]));

	// Initialize all optional columns as hidden by default
	$effect(() => {
		columns.forEach((col) => {
			if (col.optional && !(col.id in shownOptional)) {
				shownOptional[col.id] = false;
			}
		});
	});

	function handleRowClick(row: any) {
		onrowclick?.(row);
	}
</script>

<div class="bg-white rounded-xl shadow-md border border-gray-200 overflow-hidden">
  <!-- Header with column toggle -->
  {#if optionalColumns.length > 0}
    <div class="flex items-center justify-end px-6 py-3 bg-gray-50 border-b border-gray-200">
      <CheckboxDropdown 
        id="column-visibility"
		ariaLabel="Toggle Columns"
        options={optionalColumns}
        bind:selected={shownOptional}
      />
    </div>
  {/if}
  
  <div class="overflow-x-auto">
    <table class="w-full">
      <thead class="bg-gray-50 border-b border-gray-200">
        <tr>
          {#each visibleColumns as column}
            <th
              class="px-6 py-3 text-{column.align || 'left'} text-xs font-medium text-gray-600 uppercase tracking-wider whitespace-nowrap"
            >
              {column.label}
            </th>
          {/each}
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-200">
        {#if data.length === 0}
          <tr>
            <td colspan={visibleColumns.length} class="px-6 py-12 text-center text-gray-500">
              {emptyMessage}
            </td>
          </tr>
		{:else}
			{#each data as row}
				<tr onclick={() => handleRowClick(row)} class="hover:bg-gray-50 transition-colors cursor-pointer">
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
