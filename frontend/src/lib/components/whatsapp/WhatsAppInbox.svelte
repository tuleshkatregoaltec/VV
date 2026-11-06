<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import { ApiError } from '$lib/api/client'
import { whatsapp } from '$lib/api/whatsapp'
import { whatsappKeys, whatsappQueries } from '$lib/queries/whatsapp'
import WhatsAppMessage from './WhatsAppMessage.svelte'
import WhatsAppPublications from './WhatsAppPublications.svelte'

const queryClient = useQueryClient()
let selectedConnection = $state<string | null>(null)
let selectedThread = $state<string | null>(null)
let busy = $state(false)
let error = $state<string | null>(null)
const connections = createQuery(() => whatsappQueries.connections())
const notifications = createQuery(() => whatsappQueries.notifications())
const connectionId = $derived(selectedConnection ?? connections.data?.[0]?.id ?? null)
const connection = $derived(connections.data?.find((item) => item.id === connectionId))
const threads = createQuery(() => whatsappQueries.threads(connectionId))
const thread = $derived(threads.data?.find((item) => item.id === selectedThread))
const messages = createQuery(() => whatsappQueries.messages(thread?.id ?? null))
const inbox = $derived(
	(notifications.data ?? []).filter((item) => item.status === 'approval_required')
)
const loadError = $derived(
	connections.isError || notifications.isError || threads.isError || messages.isError
)
const blocked = $derived(!connection?.enabled || !!thread?.opted_out || loadError)

async function refresh() {
	await queryClient.invalidateQueries({ queryKey: whatsappKeys.all })
}

async function run(operation: () => Promise<unknown>) {
	if (busy) return
	busy = true
	error = null
	try {
		await operation()
	} catch (cause) {
		error =
			cause instanceof ApiError && cause.status === 409
				? `This review changed or is no longer available. ${cause.message} Current data has been refreshed; review it before trying again.`
				: cause instanceof Error
					? cause.message
					: 'The change could not be saved. Refresh and try again.'
	} finally {
		await refresh()
		busy = false
	}
}

async function openReview(threadId: string) {
	await run(async () => {
		for (const item of connections.data ?? []) {
			const rows = await queryClient.fetchQuery(whatsappQueries.threads(item.id))
			if (rows.some((row) => row.id === threadId)) {
				selectedConnection = item.id
				selectedThread = threadId
				return
			}
		}
		throw new Error('This conversation is no longer available to your account.')
	})
}
</script>

<div class="flex flex-wrap items-start justify-between gap-3">
	<div>
		<h1 class="text-xl font-semibold">WhatsApp</h1>
		<p class="mt-1 text-sm text-fg-3">Routine property questions can receive automatic replies. Sensitive requests wait for your review.</p>
	</div>
	<button type="button" class="ui-button px-3 py-2" disabled={busy} onclick={refresh}>Refresh inbox</button>
</div>

{#if error}<p class="mt-4 rounded-md border border-border p-3 text-sm text-error" role="alert">{error}</p>{/if}
{#if loadError}<p class="mt-4 text-sm text-error" role="alert">Could not load WhatsApp data. Refresh the inbox before making changes.</p>{/if}

<section class="mt-5 rounded-lg border border-border bg-card p-4" aria-label="Approval inbox">
	<h2 class="font-semibold">Needs your approval ({inbox.length})</h2>
	{#if notifications.isPending}<p class="mt-2 text-sm text-fg-3">Loading inbox…</p>
	{:else if !notifications.isError && !inbox.length}<p class="mt-2 text-sm text-fg-3">No replies need approval.</p>{/if}
	<ul class="mt-2 space-y-2">
		{#each inbox as item (item.id)}
			<li class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-2">
				<div class="min-w-0 flex-1"><p class="truncate text-sm">{item.content ?? 'Customer request'}</p><p class="text-xs text-fg-3">{item.reason ?? item.topic ?? 'Human review required'}</p></div>
				<button type="button" class="ui-button px-3 py-2" disabled={busy || !connections.data?.length} onclick={() => openReview(item.thread_id)}>Open review</button>
			</li>
		{/each}
	</ul>
</section>

{#if connections.isPending}<p class="mt-5 text-sm text-fg-3">Loading connections…</p>
{:else if !connections.isError && !connections.data?.length}<p class="mt-5 text-sm text-fg-3">No WhatsApp connections. Ask your administrator to connect a business number.</p>
{:else if connection}
	<section class="mt-5 rounded-lg border border-border bg-card p-4" aria-label="WhatsApp connection">
		<label for="whatsapp-connection" class="mr-3 text-sm font-medium">Business number</label>
		<select id="whatsapp-connection" class="rounded-md border border-border bg-app p-2 text-sm" value={connectionId} disabled={busy} onchange={(event) => { selectedConnection = event.currentTarget.value; selectedThread = null }}>
			{#each connections.data ?? [] as item (item.id)}<option value={item.id}>{item.display_name}</option>{/each}
		</select>
		<button type="button" role="switch" aria-checked={connection.enabled} aria-label="Automatic replies" class="ui-button ml-3 px-3 py-2" disabled={busy || connections.isError} onclick={() => run(() => whatsapp.updateConnection(connection.id, { enabled: !connection.enabled }))}>Automatic replies {connection.enabled ? 'on' : 'off'}</button>
		{#if !connection.enabled}<p class="mt-2 text-sm text-fg-3">Sending is disabled for this number, including approvals.</p>{/if}
	</section>
	{#key connection.id}<WhatsAppPublications {connection} />{/key}
	<div class="mt-4 grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
		<section class="rounded-lg border border-border bg-card p-4" aria-label="Property conversations">
			<h2 class="font-semibold">Conversations</h2>
			{#if threads.isPending}<p class="mt-3 text-sm text-fg-3">Loading conversations…</p>
			{:else if !threads.isError && !threads.data?.length}<p class="mt-3 text-sm text-fg-3">No customer conversations yet.</p>{/if}
			<ul class="mt-3 space-y-2">
				{#each threads.data ?? [] as item (item.id)}
					<li><button type="button" class="w-full rounded-md border border-border p-3 text-left text-sm hover:bg-panel" aria-pressed={thread?.id === item.id} disabled={busy} onclick={() => { selectedThread = item.id; error = null }}><span class="block break-all">{item.sender}</span><span class="text-xs text-fg-3">{item.opted_out ? 'Customer opted out' : item.paused ? 'Human handling' : 'Automation active'}</span></button></li>
				{/each}
			</ul>
		</section>
		<section aria-label="Conversation history" class="min-w-0">
			{#if thread}
				<div class="mb-3 rounded-lg border border-border bg-card p-4">
					<h2 class="font-semibold">{thread.sender}</h2>
					<p class="mt-1 text-sm text-fg-3">{thread.opted_out ? 'Customer opted out. They must send START in WhatsApp before automation can resume.' : thread.paused ? 'Human handling. Reply directly in WhatsApp; future messages will not receive automated drafts.' : 'Automation is active for this conversation.'}</p>
					<button type="button" class="ui-button mt-3 px-3 py-2" disabled={busy || threads.isError || thread.opted_out} onclick={() => run(() => thread.paused ? whatsapp.resume(thread.id) : whatsapp.takeover(thread.id))}>{thread.paused ? 'Resume automation' : 'Take over conversation'}</button>
					{#if !thread.paused}<p class="mt-2 text-xs text-fg-3">Taking over cancels unsent drafts. Continue the conversation directly in WhatsApp.</p>{/if}
				</div>
				{#if messages.isPending}<p class="text-sm text-fg-3">Loading messages…</p>
				{:else if !messages.isError && !messages.data?.length}<p class="text-sm text-fg-3">No message history yet.</p>{/if}
				<div class="space-y-3">
					{#each messages.data ?? [] as message (`${message.id}:${message.revision}`)}
						<WhatsAppMessage {message} {blocked} {busy} {run} />
					{/each}
				</div>
			{:else}<p class="p-4 text-sm text-fg-3">Select a conversation or open an inbox review.</p>{/if}
		</section>
	</div>
{/if}
