<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { SEND_STATUS, stamp } from '../../../email'
import { crmQueries } from '../../../queries'
import Chip from '../../ui/Chip.svelte'
import QueryView from '../../ui/QueryView.svelte'

/**
 * Messages with the lead. Email (Connectors › Email): every email sent from Vitevue and every
 * reply or email received, oldest first. Portal / WhatsApp messages are read only in phase 1.
 */
let { id }: { id: number } = $props()

const conversation = createQuery(() => crmQueries.leadConversation(id))
const emails = createQuery(() => crmQueries.emailThread(id))
</script>

<QueryView query={emails} rows={3}>
	{#snippet children(items)}
		{#if items.length}
			<div class="lbl">Email</div>
			<div class="thread" aria-label="Email conversation">
				{#each items as m (`${m.direction}:${m.id}`)}
					<div class={['msg', m.direction === 'out' && 'me']}>
						<div class="w">
							{m.direction === 'out' ? `To ${m.counterpart}` : m.counterpart} · {stamp(m.at)}
							{#if m.direction === 'out' && m.status}
								<Chip tone={SEND_STATUS[m.status].tone}>{SEND_STATUS[m.status].label}</Chip>
							{/if}
						</div>
						<b>{m.subject}</b>
						<div class="lc-body">{m.body}</div>
					</div>
				{/each}
			</div>
		{/if}
	{/snippet}
</QueryView>

<QueryView query={conversation} rows={3}>
	{#snippet children(messages)}
		{#if messages.length}
			<div class="thread" aria-label="Conversation">
				{#each messages as m, i (i)}
					<div class={['msg', m.from === 'agent' && 'me']}>
						<div class="w">{m.who} · {m.at}</div>
						{m.text}
					</div>
				{/each}
			</div>
		{/if}
		{#if !messages.length && !emails.data?.length}
			<div class="notice">No messages with this lead yet. Emails sent from Vitevue and their replies show here.</div>
		{:else}
			<div class="notice">Read only — reply to emails from your own inbox, and to chats from your phone.</div>
		{/if}
	{/snippet}
</QueryView>

<style>
	.lc-body {
		white-space: pre-wrap;
		margin-top: 4px;
	}
</style>
