<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Paperclip from 'lucide-svelte/icons/paperclip'
import { stamp } from '../../email'
import { crmQueries } from '../../queries'
import { openLead } from '../../stores/panel.svelte'
import Chip from '../ui/Chip.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'

/** Connectors › Email › Inbox: one received email, the lead it landed on, and its attachments' names. */
let { id }: { id: number } = $props()

const inbound = createQuery(() => crmQueries.emailInbound())
const m = $derived(inbound.data?.items.find((x) => x.id === id))
</script>

{#if m}
	<Panel
		kicker="Email received"
		title={m.subject}
		sub={`From ${m.from_name ? `${m.from_name} · ` : ''}${m.from_email} · ${stamp(m.received_at)}`}
	>
		{#snippet tags()}
			{#if m.created_lead}<Chip tone="blue">New lead</Chip>{/if}
			{#if m.send_id}<Chip tone="green">Reply to a Vitevue email</Chip>{/if}
		{/snippet}
		<div class="ei">
			<div class="ei-body">{m.body || '(empty message)'}</div>
			{#if m.attachments.length}
				<div>
					<div class="lbl">Attachments (names only, not stored)</div>
					{#each m.attachments as a (a)}
						<div class="small"><Paperclip size={12} /> {a}</div>
					{/each}
				</div>
			{/if}
			{#if m.enquiry_id !== null}
				<div>
					<button type="button" class="btn ghost sm" onclick={() => m.enquiry_id && openLead(m.enquiry_id)}>
						Open {m.lead_name ?? 'lead'}
					</button>
				</div>
			{/if}
		</div>
	</Panel>
{:else if inbound.isPending || inbound.isError}
	<PanelLoading query={inbound} kicker="Email received" />
{:else}
	<Panel kicker="Email received" title="Email not found"><p class="muted">This email is no longer in the list.</p></Panel>
{/if}

<style>
	.ei {
		display: grid;
		gap: 14px;
	}
	.ei-body {
		white-space: pre-wrap;
		font-size: 13px;
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--card-2);
		padding: 10px 12px;
	}
</style>
