<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../../api'
import { WHATSAPP_DEMO } from '../../../api/whatsappDemo'
import { crmQueries } from '../../../queries'
import Chip from '../../ui/Chip.svelte'
import QueryView from '../../ui/QueryView.svelte'
import WhatsAppConversation from '../../ui/WhatsAppConversation.svelte'

/** The lead's WhatsApp chat (Connectors › WhatsApp) on Lead › Conversation. */
let { id }: { id: number } = $props()

const status = createQuery(() => crmQueries.whatsappStatus())
const thread = createQuery(() => crmQueries.whatsappThread(id))
const lead = createQuery(() => crmQueries.lead(id))
</script>

<QueryView query={thread} rows={3}>
	{#snippet children(t)}
		{#if t.messages.length || status.data?.configured}
			<div class="lbl">
				WhatsApp{t.wa_number ? ` · ${t.wa_number}` : ''}
				{#if WHATSAPP_DEMO}<Chip tone="amber">Sample data</Chip>{/if}
			</div>
		{/if}
		{#if status.data}
			<WhatsAppConversation
				thread={t}
				name={lead.data?.name ?? null}
				configured={status.data.configured}
				connected={status.data.connected}
				sendTemplate={(tp) => crm.whatsapp.sendTemplate(id, tp)}
				reply={(body) => crm.whatsapp.reply(id, body)}
			/>
		{/if}
	{/snippet}
</QueryView>

<style>
	.lbl {
		display: flex;
		align-items: center;
		gap: 6px;
	}
</style>
