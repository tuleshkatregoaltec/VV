<script lang="ts">
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

function select(option: string, close: () => void) {
	value = option
	onchange?.(option)
	close()
}
</script>

<BaseDropdown {id} {ariaLabel} displayValue={value}>
	{#snippet children({ close })}
		<ul class="max-h-60 overflow-y-auto p-1.5">
			{#each options as option (option)}
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
		</ul>
	{/snippet}
</BaseDropdown>
