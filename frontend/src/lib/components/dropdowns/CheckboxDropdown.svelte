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

let selectedCount = $derived(Object.values(selected).filter(Boolean).length)

function toggleOption(optionId: string) {
	const newSelected = { ...selected, [optionId]: !selected[optionId] }
	selected = newSelected
	onchange?.(newSelected)
}
</script>

<BaseDropdown {id} {ariaLabel} displayValue="" align="right">
	{#snippet button({ toggle, isOpen })}
		<button
			type="button"
			class="relative rounded-md border border-[var(--color-border)] bg-white p-2 transition-colors hover:border-[var(--color-border-strong)] hover:bg-slate-50"
			onclick={toggle}
			aria-label={`Toggle options for ${ariaLabel}`}
			aria-haspopup="listbox"
			aria-expanded={isOpen}
		>
			<svg
				class="h-5 w-5 text-[var(--color-fg-3)]"
				fill="none"
				viewBox="0 0 24 24"
				stroke="currentColor"
				aria-hidden="true"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M4 6h16M4 12h16M4 18h16"
				/>
			</svg>
			{#if selectedCount > 0}
				<span
					class="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-sm bg-[var(--color-navy-900)] text-xs font-medium text-[var(--color-fg-on-navy)]"
				>
					{selectedCount}
				</span>
			{/if}
		</button>
	{/snippet}

	{#snippet children({ close })}
		<div class="p-1.5" role="listbox" aria-multiselectable="true" tabindex="-1">
			{#each options as option (option.id)}
				<label
					class="group flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors hover:bg-slate-50"
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
						{#if selected[option.id]}
							<svg
								class="w-3 h-3 text-white absolute left-0.5 pointer-events-none"
								fill="currentColor"
								viewBox="0 0 12 12"
								aria-hidden="true"
							>
								<path d="M10.28 2.28L4.5 8.06 1.72 5.28l.56-.56L4.5 6.94l5.22-5.22.56.56z" />
							</svg>
						{/if}
					</div>
					<span
						id="{id}-{option.id}-label"
						class="select-none text-[var(--color-fg-2)] group-hover:text-[var(--color-fg-1)]"
					>
						{option.label}
					</span>
				</label>
			{/each}
		</div>
	{/snippet}
</BaseDropdown>
