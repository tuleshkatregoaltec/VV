<script lang="ts">
import { freshnessOf } from '$lib/utils/dataFreshness'

let {
	newestPublishedAt,
	now = new Date()
}: { newestPublishedAt: string | null | undefined; now?: Date } = $props()

const freshness = $derived(freshnessOf(newestPublishedAt, now))
</script>

{#if freshness}
	<p class="text-xs {freshness.stale ? 'text-warning' : 'text-fg-4'}">
		Newest article: <time datetime={newestPublishedAt ?? undefined}>{freshness.date}</time>
		({freshness.ageLabel}){#if freshness.stale}. This feed is not updating live; there are no
			newer articles than this.{/if}
	</p>
{/if}
