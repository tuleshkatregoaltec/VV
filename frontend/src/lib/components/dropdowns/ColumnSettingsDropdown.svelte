<script lang="ts">
import BaseDropdown from './BaseDropdown.svelte'

let {
	id,
	ariaLabel,
	options = [],
	selected = $bindable({}),
	onchange
}: {
	id: string
	ariaLabel: string
	options?: Array<{ id: string; label: string }>
	selected?: Record<string, boolean>
	onchange?: (selected: Record<string, boolean>) => void
} = $props()

function toggleOption(optionId: string) {
	const newSelected = { ...selected, [optionId]: !selected[optionId] }
	selected = newSelected
	onchange?.(newSelected)
}

function showAll() {
	const newSelected: Record<string, boolean> = {}
	for (const opt of options) {
		newSelected[opt.id] = true
	}
	selected = newSelected
	onchange?.(newSelected)
}

function hideAll() {
	const newSelected: Record<string, boolean> = {}
	for (const opt of options) {
		newSelected[opt.id] = false
	}
	selected = newSelected
	onchange?.(newSelected)
}
</script>

<BaseDropdown {id} {ariaLabel} displayValue="" align="right">
	{#snippet button({ toggle, isOpen })}
		<button
			type="button"
			class="flex items-center gap-2 rounded-md border border-[var(--color-border)] bg-white p-2 text-[var(--color-fg-3)] transition-colors hover:border-[var(--color-border-strong)] hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			onclick={toggle}
			aria-label={ariaLabel}
			aria-haspopup="listbox"
			aria-expanded={isOpen}
		>
			<!-- Settings gear icon -->
			<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
				/>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
				/>
			</svg>
			<span class="text-sm font-medium">Columns</span>
		</button>
	{/snippet}

	{#snippet children({ close })}
		<div class="min-w-[200px]" role="listbox" aria-multiselectable="true" tabindex="-1">
			<!-- Header with quick actions -->
			<div class="flex items-center justify-between border-b border-[var(--color-border)] px-3 py-2">
				<span class="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--color-fg-4)]">Show Columns</span>
				<div class="flex gap-2">
					<button
						type="button"
						onclick={showAll}
						class="text-xs font-medium text-[var(--color-navy-700)] hover:text-[var(--color-navy-900)]"
					>
						All
					</button>
					<span class="text-[var(--color-border-strong)]">|</span>
					<button
						type="button"
						onclick={hideAll}
						class="text-xs font-medium text-[var(--color-navy-700)] hover:text-[var(--color-navy-900)]"
					>
						None
					</button>
				</div>
			</div>

			<!-- Column checkboxes -->
			<div class="max-h-[300px] overflow-y-auto p-1.5">
				{#each options as option (option.id)}
					<label
						class="group flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 transition-colors hover:bg-slate-50"
					>
						<div class="relative flex items-center">
							<input
								type="checkbox"
								id="{id}-{option.id}"
								checked={selected[option.id] || false}
								onchange={() => toggleOption(option.id)}
								class="h-4 w-4 cursor-pointer rounded-sm border-[var(--color-border-strong)] accent-[var(--color-navy-900)] text-[var(--color-navy-900)] focus:ring-2 focus:ring-[rgba(11,27,43,0.12)]"
								aria-checked={selected[option.id] ? 'true' : 'false'}
								aria-labelledby="{id}-{option.id}-label"
							/>
						</div>
						<span
							id="{id}-{option.id}-label"
							class="select-none text-sm group-hover:text-[var(--color-fg-1)] {selected[option.id]
								? 'text-[var(--color-fg-1)]'
								: 'text-[var(--color-fg-4)]'}"
						>
							{option.label}
						</span>
					</label>
				{/each}
			</div>
		</div>
	{/snippet}
</BaseDropdown>
