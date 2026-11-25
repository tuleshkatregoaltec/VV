<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import { onMount } from 'svelte'
import { chat } from '$lib/api/chat'
import { crmKeys } from '$lib/crm/queries'
import { chatKeys, chatQueries, chatScope } from '$lib/queries/chat'

let { actionId }: { actionId: string } = $props()
const queryClient = useQueryClient()
const proposal = createQuery(() => chatQueries.action(actionId))
let pending = $state(false)
let error = $state<string | null>(null)
let now = $state(Date.now())
const action = $derived(proposal.data)
const expired = $derived(action ? new Date(action.expires_at).getTime() <= now : false)
const unavailable = $derived(action?.preview.available === false)
const canConfirm = $derived(
	action?.status === 'awaiting_confirmation' && !expired && !unavailable && !proposal.isError
)
const labels: Record<string, string> = {
	awaiting_confirmation: 'Awaiting your confirmation',
	unavailable: 'This action is unavailable — request a new proposal',
	succeeded: 'Completed',
	partially_succeeded: 'Partly completed — saved in the CRM, external update failed',
	cancelled: 'Cancelled',
	expired: 'Expired — request a new proposal',
	failed: 'Failed — no success confirmed',
	not_connected: 'Provider not connected — nothing sent or booked',
	queued: 'Queued — completion not confirmed',
	unknown: 'Outcome unknown — do not repeat until checked'
}
const status = $derived(
	unavailable
		? 'unavailable'
		: action?.status === 'awaiting_confirmation' && expired
			? 'expired'
			: action?.status
)

onMount(() => {
	const timer = setInterval(() => {
		now = Date.now()
	}, 1000)
	return () => clearInterval(timer)
})

function previewValue(value: unknown): string {
	if (value === null) return 'None'
	if (Array.isArray(value) && value.every((item) => typeof item === 'string'))
		return value.length ? value.join(', ') : 'None'
	if (typeof value === 'object') return JSON.stringify(value, null, 2)
	return String(value)
}

async function decide(confirm: boolean) {
	if (pending || !canConfirm) return
	pending = true
	error = null
	try {
		const updated = await (confirm ? chat.confirmAction(actionId) : chat.cancelAction(actionId))
		queryClient.setQueryData(chatKeys.action(actionId), updated)
		// The answer above this card is rebuilt from the action's status on the server.
		await queryClient.invalidateQueries({ queryKey: [...chatKeys.all, chatScope(), 'messages'] })
		if (updated.status === 'succeeded' || updated.status === 'partially_succeeded') {
			await queryClient.invalidateQueries({ queryKey: crmKeys.all })
		}
	} catch {
		error = 'Could not confirm this change. Review the current status before trying again.'
		await proposal.refetch()
	} finally {
		pending = false
	}
}
</script>

<section class="rounded-lg border border-border bg-card p-4 text-sm" aria-label="Action review" aria-busy={pending}>
	{#if proposal.isLoading}
		<p class="text-fg-4">Loading action for review…</p>
	{:else if action}
		<h3 class="font-semibold text-fg-1">{action.title}</h3>
		<p class="mt-1 text-xs text-fg-3" role="status">{status ? labels[status] : 'Status unavailable'}</p>
		{#if action.status !== 'awaiting_confirmation' && typeof action.result?.message === 'string'}
			<p class="mt-1 text-sm text-fg-2">{action.result.message}</p>
		{/if}
		<dl class="my-3 space-y-2">
			{#each Object.entries(action.preview) as [field, value] (field)}
				<div>
					<dt class="text-xs font-medium text-fg-4">{field.replaceAll('_', ' ')}</dt>
					<dd class="whitespace-pre-wrap break-words text-fg-2">{previewValue(value)}</dd>
				</div>
			{/each}
		</dl>
		<p class="text-xs text-fg-4">Expires {new Date(action.expires_at).toLocaleString()}</p>
		{#if canConfirm}
			<p class="mt-2 text-xs text-fg-3">Confirm applies exactly the changes shown above.</p>
			<div class="mt-3 flex gap-2">
				<button type="button" class="ui-button bg-navy px-3 py-2 text-bone" disabled={pending} onclick={() => decide(true)}>{pending ? 'Working…' : 'Confirm'}</button>
				<button type="button" class="ui-button px-3 py-2" disabled={pending} onclick={() => decide(false)}>Cancel</button>
			</div>
		{/if}
	{/if}
	{#if error || proposal.isError}
		<p class="mt-2 text-xs text-error" role="alert">{error ?? 'This action is unavailable. It may have expired or you may no longer have access.'}</p>
		<button type="button" class="ui-button mt-2 px-3 py-2 text-xs" disabled={pending} onclick={() => proposal.refetch()}>Refresh status</button>
	{/if}
</section>
