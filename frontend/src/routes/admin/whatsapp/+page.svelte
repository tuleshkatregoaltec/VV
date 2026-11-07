<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { ApiError } from '$lib/api/client'
import type { AdminConnectionRow } from '$lib/api/whatsapp-connect'
import { whatsappConnectQueries } from '$lib/queries/whatsapp-connect'
import { automationView } from '$lib/whatsapp/connect-state'

const query = createQuery(() => whatsappConnectQueries.admin())
const data = $derived(query.data)
const error = $derived(
	query.isError
		? query.error instanceof ApiError
			? query.error.message
			: 'Failed to load WhatsApp connections'
		: ''
)

const fmt = (value: string | null) =>
	value
		? new Date(value).toLocaleString(undefined, {
				day: 'numeric',
				month: 'short',
				year: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			})
		: '—'

function badge(row: AdminConnectionRow) {
	if (row.status === 'connected') return 'bg-success-bg text-success'
	if (row.status === 'disconnected') return 'bg-bone-muted text-fg-3'
	return 'bg-warning-bg text-warning'
}

const pausedReason: Record<string, string> = {
	assistant_disabled: 'Assistant off server-wide',
	intake_disabled: 'Intake off server-wide'
}

const sendBadge = (value: AdminConnectionRow['can_send_message']) =>
	value === 'BLOCKED' ? 'text-error' : value === 'LIMITED' ? 'text-warning' : 'text-fg-3'
</script>

<div class="flex flex-col gap-5">
	<section class="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
		<div class="bg-navy px-5 py-5 text-bone">
			<p class="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">Admin</p>
			<h1 class="mt-2 font-display text-3xl leading-tight tracking-[var(--tracking-display)] text-bone">
				WhatsApp connections
			</h1>
			<p class="mt-2 max-w-2xl text-sm leading-6 text-slate-300">
				How many agents have connected their WhatsApp number, and how many have automatic replies on, and how many are switched on but paused by Vitevue.
			</p>
		</div>
	</section>

	{#if query.isPending}
		<div class="py-16 text-center text-fg-4">Loading...</div>
	{:else if error}
		<div class="flex items-center justify-between gap-3 rounded-lg border border-[rgba(163,36,36,0.2)] bg-error-bg p-4 text-sm text-error" role="alert">
			<span>{error}</span>
			<button class="rounded-md border border-border bg-white px-3 py-1.5 text-fg-2" onclick={() => query.refetch()}>Retry</button>
		</div>
	{:else if data}
		<dl class="grid grid-cols-2 gap-3 sm:grid-cols-4">
			{#each [['Numbers on record', data.total], ['Connected now', data.connected], ['Automatic replies on', data.automation_on], ['Automatic replies paused', data.automation_paused]] as [label, value] (label)}
				<div class="rounded-lg border border-border bg-white p-4 shadow-sm">
					<dt class="text-xs font-semibold uppercase tracking-wider text-fg-4">{label}</dt>
					<dd class="mt-1 font-display text-3xl text-fg-1">{value}</dd>
				</div>
			{/each}
		</dl>

		{#if data.items.length === 0}
			<div class="py-16 text-center text-fg-4">No agent has connected WhatsApp yet.</div>
		{:else}
			<div class="overflow-x-auto rounded-lg border border-border bg-white shadow-sm">
				<table class="min-w-full divide-y divide-border">
					<thead>
						<tr class="bg-slate-50">
							{#each ['Agent', 'Number', 'Status', 'Replies', 'Contacts', 'Blocked', 'Last message', 'Connected'] as heading (heading)}
								<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-fg-4">{heading}</th>
							{/each}
						</tr>
					</thead>
					<tbody class="divide-y divide-border">
						{#each data.items as row (row.connection_id)}
							{@const replies = automationView(row, row.status)}
							<tr>
								<td class="px-4 py-3 text-sm">
									<div class="font-medium text-fg-1">{row.user_email ?? row.user_id}</div>
									<div class="text-xs text-fg-4">{row.organization_name ?? '—'}</div>
								</td>
								<td class="whitespace-nowrap px-4 py-3 text-sm text-fg-2">
									<div>{row.display_phone_number ?? row.phone_number_id}</div>
									{#if row.display_name}<div class="text-xs text-fg-4">{row.display_name}</div>{/if}
								</td>
								<td class="px-4 py-3 text-sm">
									<span class="inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium {badge(row)}">{row.status}</span>
									{#if row.can_send_message && row.can_send_message !== 'AVAILABLE'}
										<div class="mt-1 text-xs {sendBadge(row.can_send_message)}">Sending {row.can_send_message.toLowerCase()}</div>
									{/if}
								</td>
								<td class="px-4 py-3 text-sm text-fg-2">
									{#if replies.kind === 'disconnected'}
										<span class="inline-flex rounded-full bg-warning-bg px-2.5 py-0.5 text-xs font-medium text-warning">Not connected</span>
										<div class="mt-1 whitespace-nowrap text-xs text-fg-4">Agent must reconnect</div>
									{:else if replies.kind === 'paused'}
										<span class="inline-flex rounded-full bg-warning-bg px-2.5 py-0.5 text-xs font-medium text-warning">Paused</span>
										<div class="mt-1 whitespace-nowrap text-xs text-fg-4">{pausedReason[row.automation_paused_reason ?? ''] ?? 'Paused by Vitevue'}</div>
									{:else}{replies.label}{/if}
								</td>
								<td class="px-4 py-3 text-sm text-fg-2">
									{row.contacts_total}
									{#if !row.contacts_synced_at && row.status === 'connected'}<span class="text-xs text-fg-4"> syncing</span>{/if}
								</td>
								<td class="px-4 py-3 text-sm text-fg-2">{row.contacts_blocked}</td>
								<td class="px-4 py-3 text-sm whitespace-nowrap text-fg-3">{fmt(row.last_message_at)}</td>
								<td class="px-4 py-3 text-sm whitespace-nowrap text-fg-3">{fmt(row.connected_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{/if}
</div>
