<script lang="ts">
import { TriangleAlert } from 'lucide-svelte'
import { freshnessOf } from '$lib/utils/dataFreshness'

let { snapshotAt, now = new Date() }: { snapshotAt: string | null | undefined; now?: Date } =
	$props()

const freshness = $derived(freshnessOf(snapshotAt, now))
</script>

<section
	class="flex items-start gap-3 rounded-lg border px-4 py-3 {freshness?.stale || !freshness
		? 'border-warning-border bg-warning-bg text-warning'
		: 'border-border bg-panel text-fg-2'}"
	aria-label="Listing data snapshot"
>
	<TriangleAlert size={16} class="mt-0.5 shrink-0" />
	<div class="min-w-0 text-xs leading-5">
		{#if freshness}
			<p class="text-sm font-semibold">
				Listings captured on <time datetime={snapshotAt ?? undefined}>{freshness.date}</time>
				<span class="font-normal">({freshness.ageLabel})</span>
			</p>
			<p>
				This is a snapshot of portal listings, not a live feed. Prices and availability have not
				been confirmed since that date, and a listing shown here may already be let, sold or
				withdrawn. Listing ages are counted to the capture date, not to today.
			</p>
		{:else}
			<p class="text-sm font-semibold">Capture date unavailable</p>
			<p>
				These are snapshot portal listings, not a live feed. Prices and availability have not been
				confirmed as current.
			</p>
		{/if}
	</div>
</section>
