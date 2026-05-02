<script lang="ts">
import ColumnSettingsDropdown from '$lib/components/dropdowns/ColumnSettingsDropdown.svelte'

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
		id: string
		label: string
		align?: 'left' | 'center' | 'right'
		format?: (value: any, row: any) => string
		badge?: boolean
		highlighted?: boolean
		defaultVisible?: boolean
	}>
	data?: Array<Record<string, any>>
	emptyMessage?: string
	loading?: boolean
	onrowclick?: (row: any) => void
	// Selection
	selectable?: boolean
	selectedIds?: Set<string>
	getRowId?: (row: any) => string
} = $props()

// Track which columns are visible (using column id as key)
let columnVisibility: Record<string, boolean> = $state({})
let hoveredRowId: string | null = $state(null)
let lastColumnsKey = ''

// Initialize column visibility from defaultVisible property when columns change
$effect(() => {
	// Create a key based on column IDs to detect when columns have changed
	const columnsKey = columns.map((c) => c.id).join(',')

	if (columnsKey !== lastColumnsKey) {
		// Columns have changed - reinitialize visibility
		const newVisibility: Record<string, boolean> = {}
		for (const col of columns) {
			// Preserve existing visibility preference if column still exists
			if (col.id in columnVisibility) {
				newVisibility[col.id] = columnVisibility[col.id]
			} else {
				newVisibility[col.id] = col.defaultVisible !== false
			}
		}
		columnVisibility = newVisibility
		lastColumnsKey = columnsKey
	}
})

// All columns are available for toggling
let allColumnOptions = $derived(columns.map((c) => ({ id: c.id, label: c.label })))

let visibleColumns = $derived(columns.filter((c) => columnVisibility[c.id]))

// Selection mode is active when any items are selected
let inSelectionMode = $derived(selectable && selectedIds.size > 0)

// Get all row IDs on current page
let allRowIds = $derived(data.map((row) => getRowId?.(row) ?? row.id))

// Check if all rows on current page are selected
let allSelected = $derived(
	selectable && data.length > 0 && allRowIds.every((id) => selectedIds.has(id))
)

// Check if some (but not all) rows on current page are selected
let someSelected = $derived(
	selectable && allRowIds.some((id) => selectedIds.has(id)) && !allSelected
)

function handleRowClick(row: any) {
	onrowclick?.(row)
}

function toggleSelectAll() {
	const newSet = new Set(selectedIds)
	if (allSelected) {
		// Deselect all on current page
		allRowIds.forEach((id) => {
			newSet.delete(id)
		})
	} else {
		// Select all on current page
		allRowIds.forEach((id) => {
			newSet.add(id)
		})
	}
	selectedIds = newSet
}

function toggleRow(row: any, event: Event) {
	event.stopPropagation() // Prevent row click handler
	const id = getRowId?.(row) ?? row.id
	const newSet = new Set(selectedIds)
	if (newSet.has(id)) {
		newSet.delete(id)
	} else {
		newSet.add(id)
	}
	selectedIds = newSet
}

function isRowSelected(row: any): boolean {
	const id = getRowId?.(row) ?? row.id
	return selectedIds.has(id)
}

function showCheckbox(row: any): boolean {
	if (!selectable) return false
	// Always show in selection mode, or when hovering this row
	const id = getRowId?.(row) ?? row.id
	return inSelectionMode || hoveredRowId === id
}

function getRenderKey(row: any, index: number): string {
	const baseId = String(getRowId?.(row) ?? row.id ?? 'row')
	return [
		baseId,
		row.transaction_id,
		row.contract_id,
		row.date,
		row.startDate,
		row.endDate,
		row.project,
		row.building,
		index
	]
		.filter((value) => value != null && value !== '')
		.join(':')
}
</script>

<div class="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
	<!-- Column settings dropdown in upper right -->
	<div class="flex items-center justify-end border-b border-[var(--color-border)] bg-white px-4 py-2">
		<ColumnSettingsDropdown
			id="column-visibility"
			ariaLabel="Column Settings"
			options={allColumnOptions}
			bind:selected={columnVisibility}
		/>
	</div>

	<div class="overflow-x-auto">
		<table class="w-full">
			<thead class="border-b border-[var(--color-border)] bg-slate-50">
				<tr>
					{#if selectable}
						<th class="w-12 px-4 py-3">
							{#if inSelectionMode}
								<input
									type="checkbox"
									checked={allSelected}
									indeterminate={someSelected}
									onchange={toggleSelectAll}
									class="h-4 w-4 cursor-pointer rounded-sm border-[var(--color-border-strong)] accent-[var(--color-navy-900)] text-[var(--color-navy-900)] focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
									aria-label="Select all transactions on this page"
								/>
							{/if}
						</th>
					{/if}
					{#each visibleColumns as column (column.id)}
						<th
							class="whitespace-nowrap px-4 py-3 text-{column.align ||
								'left'} font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--color-fg-4)]"
						>
							{column.label}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody class="divide-y divide-slate-100">
				{#if loading}
					<tr>
						<td
							colspan={visibleColumns.length + (selectable ? 1 : 0)}
							class="px-6 py-16 text-center"
						>
							<div class="flex flex-col items-center gap-3">
								<div
									class="inline-block h-8 w-8 animate-spin rounded-full border-b-2 border-[var(--color-navy-900)]"
								></div>
								<span class="text-sm text-[var(--color-fg-4)]">Loading...</span>
							</div>
						</td>
					</tr>
				{:else if data.length === 0}
					<tr>
						<td
							colspan={visibleColumns.length + (selectable ? 1 : 0)}
							class="px-6 py-12 text-center text-sm text-[var(--color-fg-4)]"
						>
							{emptyMessage}
						</td>
					</tr>
				{:else}
					{#each data as row, index (getRenderKey(row, index))}
						<tr
							onmouseenter={() => {
								if (selectable) hoveredRowId = getRowId?.(row) ?? row.id;
							}}
							onmouseleave={() => {
								if (selectable) hoveredRowId = null;
							}}
							onclick={() => handleRowClick(row)}
							class="cursor-pointer transition-colors hover:bg-slate-50 {isRowSelected(row)
								? 'bg-[var(--color-navy-50)]'
								: ''}"
						>
							{#if selectable}
								<td class="w-12 px-4 py-3.5">
									<div
										class="flex items-center justify-center transition-opacity duration-150 {showCheckbox(
											row
										)
											? 'opacity-100'
											: 'opacity-0'}"
									>
										<input
											type="checkbox"
											checked={isRowSelected(row)}
											onchange={(e) => toggleRow(row, e)}
											onclick={(e) => e.stopPropagation()}
											class="h-4 w-4 cursor-pointer rounded-sm border-[var(--color-border-strong)] accent-[var(--color-navy-900)] text-[var(--color-navy-900)] focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
											aria-label="Select transaction"
										/>
									</div>
								</td>
							{/if}
							{#each visibleColumns as column (column.id)}
								<td
									class="whitespace-nowrap px-4 py-3.5 text-{column.align ||
										'left'} text-[13px] tabular-nums {column.highlighted
										? 'font-semibold text-[var(--color-navy-900)]'
										: 'text-[var(--color-fg-1)]'}"
								>
									{#if column.badge}
										<span
											class="inline-flex rounded-sm bg-slate-100 px-2.5 py-1 font-mono text-[11px] font-medium tracking-[0.02em] text-[var(--color-fg-2)]"
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
