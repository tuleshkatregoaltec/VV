<script lang="ts">
let {
	message,
	retry,
	fetching = false
}: {
	message: string
	retry: () => unknown
	fetching?: boolean
} = $props()
</script>

<div role="alert" class="rounded-lg border border-error bg-error-bg p-4 text-sm text-error">
	<p>{message}</p>
	<button type="button" class="mt-2 underline disabled:opacity-50" disabled={fetching} onclick={retry}>Retry</button>
</div>
