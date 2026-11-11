<script lang="ts">
import ExternalLink from 'lucide-svelte/icons/external-link'
import TriangleAlert from 'lucide-svelte/icons/triangle-alert'
import { ApiError } from '$lib/api/client'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappConnectKeys } from '$lib/queries/whatsapp-connect'
import {
	healthErrorText,
	qualityLabel,
	sendingWarning,
	WHATSAPP_MANAGER_URL
} from '$lib/whatsapp/connect-state'

// A section of the connected card: the number, how Meta rates it, and how to disconnect it.
let {
	status,
	ondisconnected
}: { status: AgentConnectionStatus; ondisconnected: (next: AgentConnectionStatus) => void } =
	$props()
const queryClient = getQueryClient()

let confirming = $state(false)
let working = $state(false)

const warning = $derived(sendingWarning(status.can_send_message))
const since = $derived(
	status.connected_at
		? new Date(status.connected_at).toLocaleDateString(undefined, {
				day: 'numeric',
				month: 'short',
				year: 'numeric'
			})
		: '—'
)
const sending = $derived(
	status.can_send_message === 'AVAILABLE'
		? 'Available'
		: status.can_send_message === 'LIMITED'
			? 'Limited'
			: status.can_send_message === 'BLOCKED'
				? 'Blocked by Meta'
				: 'Not reported yet'
)

async function disconnect() {
	working = true
	try {
		const next = await whatsappConnect.disconnect()
		ondisconnected(next)
		queryClient.setQueryData(whatsappConnectKeys.status(), null)
		queryClient.removeQueries({
			queryKey: whatsappConnectKeys.all,
			predicate: (q) => q.queryKey.includes('contacts')
		})
		confirming = false
		toast.show('WhatsApp disconnected. Synced contacts were deleted.')
	} catch (e) {
		confirming = false
		toast.show(
			e instanceof ApiError && e.message ? e.message : 'Could not disconnect. Try again.',
			{ tone: 'error' }
		)
	} finally {
		working = false
	}
}
</script>

<section class="part" aria-label="Your WhatsApp number">
	<div class="top">
		<div class="who">
			<span class="num">{status.display_phone_number ?? 'Number not shown'}</span>
			{#if status.display_name}<span class="name">{status.display_name}</span>{/if}
		</div>
		<span class="chip green">Connected</span>
	</div>

	<dl class="meta">
		<div><dt>Since</dt><dd>{since}</dd></div>
		<div><dt>Number quality</dt><dd>{qualityLabel(status.quality_rating)}</dd></div>
		<div><dt>Sending</dt><dd>{sending}</dd></div>
	</dl>

	{#if warning}
		<div class={['alert', warning.tone]} role="alert">
			<TriangleAlert size={16} aria-hidden="true" />
			<div><b>{warning.title}</b><span>{warning.text}</span></div>
		</div>
	{/if}
	{#each status.health_errors as err, i (i)}
		<div class="alert amber" role="alert">
			<TriangleAlert size={16} aria-hidden="true" />
			<div><span>{healthErrorText(err)}</span></div>
		</div>
	{/each}

	<div class="foot">
		<p>
			Meta bills replies after 1,000 free a month.
			<a href={WHATSAPP_MANAGER_URL} target="_blank" rel="noopener noreferrer">Check your payment method <ExternalLink size={12} aria-hidden="true" /></a>
		</p>
		<button type="button" class="btn ghost sm" onclick={() => (confirming = true)} disabled={working}>Disconnect WhatsApp</button>
	</div>
</section>

<ConfirmModal
	open={confirming}
	title="Disconnect WhatsApp?"
	message="Vitevue will stop answering enquiries from this number and permanently delete the contacts it synced, including your block list. Your chats stay on your phone."
	confirmText={working ? 'Disconnecting…' : 'Disconnect WhatsApp'}
	cancelText="Keep connected"
	onConfirm={disconnect}
	onCancel={() => (confirming = false)}
/>

<style>
.part { display: grid; gap: 12px; padding: 18px 20px; }
.top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.who { display: grid; gap: 2px; min-width: 0; }
.num { font-size: 24px; font-weight: 600; letter-spacing: -.015em; line-height: 1.2; font-variant-numeric: tabular-nums; }
.name { font-size: 13.5px; color: var(--text2); }
.meta { margin: 0; display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; }
.meta div { display: flex; gap: 6px; }
dt { color: var(--text3); }
dd { margin: 0; color: var(--text); }
.alert { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 8px; font-size: 13.5px; }
.alert > div { display: grid; gap: 2px; }
.alert b { font-weight: 600; }
.alert :global(svg) { flex: none; margin-top: 2px; }
.alert.amber { background: var(--amber-bg); color: var(--amber); }
.alert.red { background: var(--red-bg); color: var(--red); }
.alert.amber span, .alert.red span { color: var(--text); }
.foot { display: flex; justify-content: space-between; align-items: center; gap: 8px 16px; flex-wrap: wrap; }
.foot p { margin: 0; font-size: 12.5px; color: var(--text3); }
.foot a { color: var(--accent); font-weight: 500; display: inline-flex; gap: 4px; align-items: center; margin-left: 2px; }
.foot a:hover { text-decoration: underline; }
</style>
