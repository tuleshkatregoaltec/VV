<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../api'
import { WHATSAPP_DEMO } from '../../api/whatsappDemo'
import { crmQueries } from '../../queries'
import { openLead } from '../../stores/panel.svelte'
import { chatName, chatSub, potential } from '../../whatsapp'
import Chip from '../ui/Chip.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'
import QueryView from '../ui/QueryView.svelte'
import StageChip from '../ui/StageChip.svelte'
import WhatsAppConversation from '../ui/WhatsAppConversation.svelte'

/** Connectors › WhatsApp › a chat: the conversation with one number, and the lead it is on. */
let { waId }: { waId: string } = $props()

const status = createQuery(() => crmQueries.whatsappStatus())
const chats = createQuery(() => crmQueries.whatsappChats())
const thread = createQuery(() => crmQueries.whatsappChat(waId))
const c = $derived(chats.data?.find((x) => x.wa_id === waId))
</script>

{#if chats.data}
	<Panel
		kicker="WhatsApp"
		title={c ? chatName(c) : `+${waId}`}
		sub={c ? chatSub(c) : ''}
	>
		{#snippet tags()}
			{#if c?.lead_id === null}<Chip tone="amber">Needs review</Chip>{/if}
			{#if c?.lead_stage}<StageChip stage={c.lead_stage} />{/if}
			{#if c && c.lead_score !== null}
				<Chip tone={potential(c.lead_score).band === '' ? 'green' : potential(c.lead_score).band === 'mid' ? 'amber' : 'neutral'}>
					{potential(c.lead_score).label} potential · {c.lead_score}%
				</Chip>
			{/if}
			{#if WHATSAPP_DEMO}<Chip tone="amber">Sample data</Chip>{/if}
		{/snippet}
		<div class="wc">
			{#if c?.lead_id}
				<div>
					<button type="button" class="btn ghost sm" onclick={() => c.lead_id && openLead(c.lead_id, 'conversation')}>
						Open lead
					</button>
				</div>
			{/if}
			<QueryView query={thread} rows={3}>
				{#snippet children(t)}
					{#if status.data}
						<WhatsAppConversation
							thread={t}
							name={c?.lead_name ?? c?.contact_name ?? null}
							configured={status.data.configured}
							sendTemplate={(tp) => crm.whatsapp.chatSendTemplate(waId, tp)}
							reply={(body) => crm.whatsapp.chatReply(waId, body)}
						/>
					{/if}
				{/snippet}
			</QueryView>
		</div>
	</Panel>
{:else}
	<PanelLoading query={chats} kicker="WhatsApp" />
{/if}

<style>
	.wc {
		display: grid;
		gap: 0.6rem;
	}
</style>
