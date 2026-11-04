<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../api'
import { stamp } from '../../email'
import { crmQueries } from '../../queries'
import { openLead } from '../../stores/panel.svelte'
import { windowHoursLeft } from '../../whatsapp'
import { errorText } from '../../write'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import QueryView from '../ui/QueryView.svelte'
import Skeleton from '../ui/Skeleton.svelte'
import WhatsAppConversation from '../ui/WhatsAppConversation.svelte'

/**
 * Connectors › WhatsApp › Campaign inbox (organization owners): people who wrote back to the
 * campaign number. Answer inside their 24-hour window, or open their lead to hand them to an agent.
 */
const chats = createQuery(() => crmQueries.whatsappCampaignChats())
let openWa = $state<string | null>(null)
const thread = createQuery(() => ({
	...crmQueries.whatsappCampaignChat(openWa ?? ''),
	enabled: openWa !== null
}))
const open = $derived(chats.data?.find((c) => c.wa_id === openWa))
</script>

<div class="filters">
	<span class="sub">Replies to the campaign number. Open a lead to hand the conversation to its agent.</span>
</div>

{#if chats.data}
	<div class="card">
		<div class="tblwrap">
			<table class="tbl">
				<thead><tr><th>Contact</th><th>Last message</th><th>Reply</th><th>When</th></tr></thead>
				<tbody>
					{#each chats.data as c (c.wa_id)}
						{@const hours = windowHoursLeft(c.window_ends_at)}
						<tr class="row">
							<td>
								<button type="button" class="rowlink" onclick={() => (openWa = openWa === c.wa_id ? null : c.wa_id)}>
									{c.lead_name ?? c.contact_name ?? `+${c.wa_id}`}
								</button>
								{#if c.unread}<Chip tone="blue">{c.unread} new</Chip>{/if}
								<div class="sub">+{c.wa_id}</div>
								{#if c.lead_id !== null}
									<button type="button" class="btn plain sm" onclick={() => c.lead_id && openLead(c.lead_id, 'conversation')}>Open lead</button>
								{:else}
									<Chip tone="amber">Not on a lead</Chip>
								{/if}
							</td>
							<td data-label="Last message"><span class="sub">{c.last_direction === 'out' ? 'You: ' : ''}{c.last_body}</span></td>
							<td data-label="Reply">
								{#if hours}<Chip tone="green">Open · {hours}h left</Chip>{:else}<span class="sub">Closed</span>{/if}
							</td>
							<td data-label="When" class="nowrap">{stamp(c.last_at)}</td>
						</tr>
					{:else}
						<tr><td colspan="4"><Empty text="No replies to campaigns yet." /></td></tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
{:else if chats.isError}
	<div class="card"><ErrorLine message={errorText(chats.error)} onretry={() => chats.refetch()} /></div>
{:else}
	<div class="card"><Skeleton rows={3} /></div>
{/if}

{#if openWa !== null}
	{@const waId = openWa}
	<div class="card wa-thread">
		<QueryView query={thread} rows={3}>
			{#snippet children(t)}
				<WhatsAppConversation
					thread={t}
					name={open?.lead_name ?? open?.contact_name ?? null}
					configured
					reply={(body) => crm.whatsapp.campaigns.reply(waId, body)}
				/>
			{/snippet}
		</QueryView>
	</div>
{/if}

<style>
	.wa-thread {
		padding: 1rem;
		margin-top: 1rem;
	}
</style>
