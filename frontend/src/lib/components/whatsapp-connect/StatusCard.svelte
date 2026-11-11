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

<section class="card" aria-labelledby="status-h">
	<div class="ch">
		<h2 id="status-h">Your WhatsApp</h2>
		<span class="chip green">Connected</span>
	</div>
	<div class="cb stack">
		<div class="who">
			<span class="num">{status.display_phone_number ?? 'Number not shown'}</span>
			{#if status.display_name}<span class="muted">{status.display_name}</span>{/if}
		</div>

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

		<dl>
			<div><dt>Connected since</dt><dd>{since}</dd></div>
			<div><dt>Number quality</dt><dd>{qualityLabel(status.quality_rating)}</dd></div>
			<div><dt>Sending</dt><dd>{status.can_send_message === 'AVAILABLE' ? 'Available' : status.can_send_message === 'LIMITED' ? 'Limited' : status.can_send_message === 'BLOCKED' ? 'Blocked by Meta' : 'Not reported yet'}</dd></div>
		</dl>

		<div class="alert info">
			<div>
				<b>Check your payment method</b>
				<span>Vitevue can’t see whether you have added one. After 1,000 free replies a month, Meta bills replies to your WhatsApp account.</span>
				<a href={WHATSAPP_MANAGER_URL} target="_blank" rel="noopener noreferrer">Open WhatsApp Manager <ExternalLink size={12} aria-hidden="true" /></a>
			</div>
		</div>

		<div class="foot">
			<button type="button" class="btn danger sm" onclick={() => (confirming = true)} disabled={working}>Disconnect WhatsApp</button>
		</div>
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
.stack { display: grid; gap: 14px; }
.who { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; }
.num { font-size: 20px; font-weight: 600; letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
dl { margin: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
dt { font-family: var(--font-mono); font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--text3); }
dd { margin: 2px 0 0; font-size: 14px; }
.alert { display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: 8px; font-size: 13.5px; }
.alert > div { display: grid; gap: 2px; }
.alert b { font-weight: 600; }
.alert :global(svg) { flex: none; margin-top: 2px; }
.alert.amber { background: var(--amber-bg); color: var(--amber); }
.alert.red { background: var(--red-bg); color: var(--red); }
.alert.amber span, .alert.red span { color: var(--text); }
.alert.info { background: var(--sunk); color: var(--text2); }
.alert.info b { color: var(--text); }
.alert a { color: var(--accent); font-weight: 500; display: inline-flex; gap: 4px; align-items: center; }
.alert a:hover { text-decoration: underline; }
.foot { display: flex; justify-content: flex-end; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr 1fr; } }
</style>
