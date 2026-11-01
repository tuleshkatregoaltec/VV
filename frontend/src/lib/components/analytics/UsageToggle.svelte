<script lang="ts">
import type { Snippet } from 'svelte'
import type { AnalyticsUsage } from '$lib/api/analytics'
import {
	USAGES,
	type Usage,
	type UsageCounts,
	usageCountLabel,
	usageNote,
	usageTotal
} from '$lib/utils/analyticsUsage'

// Residential or Commercial records for the selected scope, each with its counts; an empty usage
// cannot be chosen. The note says what the figures cover and where the other records are.
let {
	counts,
	resolved,
	value,
	scope = 'this project',
	onchange,
	children
}: {
	counts: UsageCounts | undefined
	resolved: Usage
	value: AnalyticsUsage
	scope?: string
	onchange: (usage: Usage) => void
	children?: Snippet
} = $props()

// Only a usage that has no records, or one chosen for the project, needs saying; the rest is
// visible in the counts on the buttons.
const other = $derived<Usage>(resolved === 'Residential' ? 'Commercial' : 'Residential')
const showNote = $derived(
	usageTotal(counts, resolved) === 0 ||
		(value === 'auto' && resolved === 'Commercial' && usageTotal(counts, other) === 0)
)
</script>

<div class="mt-3 flex flex-col gap-1.5" data-testid="analytics-usage">
	<div class="flex flex-wrap items-center gap-3">
		<div class="ui-segmented" role="group" aria-label="Property usage">
			{#each USAGES as usage (usage)}
				{@const empty = usageTotal(counts, usage) === 0}
				<button
					type="button"
					class="ui-segmented-item flex items-baseline gap-1.5 px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:bg-transparent"
					data-active={resolved === usage}
					aria-pressed={resolved === usage}
					disabled={empty && resolved !== usage}
					title={empty ? `No ${usage.toLowerCase()} records for ${scope}` : undefined}
					onclick={() => onchange(usage)}
				>
					<span>{usage}</span>
					<span class="text-xs font-normal text-fg-4">{usageCountLabel(counts, usage)}</span>
				</button>
			{/each}
		</div>
		{@render children?.()}
	</div>
	{#if showNote}
		<p class="text-xs text-fg-4" data-testid="analytics-usage-note">
			{usageNote(resolved, value, counts, scope)}
		</p>
	{/if}
</div>
