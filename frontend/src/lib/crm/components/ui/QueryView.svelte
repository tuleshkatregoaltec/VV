<script lang="ts" generics="T">
import type { Snippet } from 'svelte'
import { errorText } from '../../write'
import ErrorLine from './ErrorLine.svelte'
import Skeleton from './Skeleton.svelte'

/**
 * Loading (skeleton rows) → error (one line + Retry) → content. When a refetch fails after
 * data has loaded, the data stays and a one-line error bar with Retry sits above it.
 */
let {
	query,
	rows = 4,
	children
}: {
	query: {
		data: T | undefined
		isError: boolean
		error: Error | null
		refetch: () => Promise<unknown>
	}
	rows?: number
	children: Snippet<[T]>
} = $props()
</script>

{#if query.data !== undefined}
	{#if query.isError}
		<ErrorLine bar message={errorText(query.error)} onretry={() => query.refetch()} />
	{/if}
	{@render children(query.data)}
{:else if query.isError}
	<ErrorLine message={errorText(query.error)} onretry={() => query.refetch()} />
{:else}
	<Skeleton {rows} />
{/if}
