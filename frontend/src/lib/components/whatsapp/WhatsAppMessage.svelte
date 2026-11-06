<script lang="ts">
import type { CustomerMessageResponse } from '$lib/api/generated/hey-api/types.gen'
import { whatsapp } from '$lib/api/whatsapp'

let {
	message,
	blocked,
	busy,
	run
}: {
	message: CustomerMessageResponse
	blocked: boolean
	busy: boolean
	run: (operation: () => Promise<unknown>) => Promise<void>
} = $props()

// The parent keys this editor by revision so a refreshed draft needs a fresh review.
let reply = $state(message.reply ?? '')
const dirty = $derived(reply !== (message.reply ?? ''))
const reviewable = $derived(message.status === 'approval_required')
const labels: Record<string, string> = {
	auto_pending: 'Automatic reply queued',
	approval_required: 'Needs your approval',
	approved: 'Approved · queued for sending',
	sending: 'Sending · outcome not yet confirmed',
	accepted: 'Accepted by WhatsApp · delivery not confirmed',
	sent: 'Accepted by WhatsApp · delivery not confirmed',
	failed: 'Reply failed · no successful send confirmed',
	unknown: 'Send outcome unknown · check WhatsApp before retrying',
	expired: 'Reply expired · customer service window closed',
	cancelled: 'Cancelled',
	ignored: 'No automated reply',
	queued: 'Queued for processing',
	classifying: 'Preparing reply'
}
</script>

<article class="rounded-lg border border-border bg-card p-4" aria-label="Customer message">
	<div class="flex flex-wrap justify-between gap-2 text-xs text-fg-3">
		<time datetime={message.sent_at}>{new Date(message.sent_at).toLocaleString()}</time>
		<span>{labels[message.status] ?? message.status.replaceAll('_', ' ')}</span>
	</div>
	<p class="mt-3 whitespace-pre-wrap break-words">{message.content ?? 'Message content unavailable'}</p>
	{#if message.reason}<p class="mt-2 text-sm text-fg-3">{message.reason}</p>{/if}
	{#if reviewable}
		<label class="mt-4 block text-sm font-medium" for={`reply-${message.id}`}>Reply draft</label>
		<textarea id={`reply-${message.id}`} class="mt-1 min-h-28 w-full rounded-md border border-border bg-app p-3 text-sm" bind:value={reply} maxlength={4000} disabled={busy || blocked}></textarea>
		<p class="mt-1 text-xs text-fg-3">Save edits before approving. Approval sends this reply only; it does not resume automation.</p>
		<div class="mt-3 flex flex-wrap gap-2">
			<button type="button" class="ui-button px-3 py-2" disabled={busy || blocked || !dirty || !reply.trim()} onclick={() => run(() => whatsapp.edit(message.id, { expected_revision: message.revision, reply }))}>Save draft</button>
			<button type="button" class="ui-button px-3 py-2" disabled={busy || blocked || dirty || !message.reply?.trim()} onclick={() => run(() => whatsapp.approve(message.id, message.revision))}>Approve reply</button>
			<button type="button" class="ui-button px-3 py-2" disabled={busy} onclick={() => run(() => whatsapp.cancel(message.id, message.revision))}>Cancel draft</button>
		</div>
	{:else if message.reply}
		<p class="mt-3 text-xs font-medium text-fg-3">Reply</p>
		<p class="mt-1 whitespace-pre-wrap break-words text-sm">{message.reply}</p>
	{/if}
</article>
