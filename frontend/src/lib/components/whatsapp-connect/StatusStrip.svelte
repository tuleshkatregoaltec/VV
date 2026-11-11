<script lang="ts">
import { ApiError } from '$lib/api/client'
import type { ConnectionResponse } from '$lib/api/generated/hey-api/types.gen'
import { whatsapp } from '$lib/api/whatsapp'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappKeys } from '$lib/queries/whatsapp'
import { whatsappConnectKeys } from '$lib/queries/whatsapp-connect'
import { sendingWarning } from '$lib/whatsapp/connect-state'

// The connected number at a glance, with the two switches an agent actually changes.
let {
	status,
	connection
}: { status: AgentConnectionStatus; connection: ConnectionResponse | null } = $props()
const queryClient = getQueryClient()

const warning = $derived(sendingWarning(status?.can_send_message))
let switching = $state<'auto' | 'market' | null>(null)

async function setReplies(enabled: boolean) {
	switching = 'auto'
	try {
		const next = await whatsappConnect.setAutomation(enabled)
		queryClient.setQueryData(whatsappConnectKeys.status(), next)
		await queryClient.invalidateQueries({ queryKey: whatsappKeys.all })
		toast.show(
			enabled
				? 'Automatic replies are on.'
				: 'Automatic replies are off. Nothing will be sent for you.'
		)
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.message
				? e.message
				: 'Could not change automatic replies. Try again.',
			{ tone: 'error' }
		)
	} finally {
		switching = null
	}
}

async function setMarket(enabled: boolean) {
	if (!connection) return
	switching = 'market'
	try {
		await whatsapp.updateConnection(connection.id, { market_data_enabled: enabled })
		await queryClient.invalidateQueries({ queryKey: whatsappKeys.all })
		toast.show(
			enabled
				? 'Replies can now quote Vitevue market figures.'
				: 'Replies will no longer quote market figures.'
		)
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.message
				? e.message
				: 'Could not change market figures. Try again.',
			{ tone: 'error' }
		)
	} finally {
		switching = null
	}
}
</script>

<section class="strip" aria-label="Your WhatsApp number">
	<div class="line">
		<span class={['dot', status.automation_active ? 'live' : 'idle']} aria-hidden="true"></span>
		<div class="id">
			<b>{status.display_phone_number ?? (status.phone_number_id ? 'Your number' : '')}</b>
			<span>{status.display_name ?? 'WhatsApp Business'}{#if warning}&nbsp;·&nbsp;<span class="warn">{warning.title}</span>{/if}</span>
		</div>
	</div>
	<div class="toggles">
		<button type="button" role="switch" class="sw" aria-checked={status.automation_enabled} disabled={switching !== null} onclick={() => setReplies(!status.automation_enabled)}>
			<span class="knob" aria-hidden="true"></span>
			<span class="sl"><b>Automatic replies</b><span>{status.automation_enabled ? (status.automation_active ? 'Answering property questions' : 'On, but paused by Vitevue') : 'Off. Nothing is sent for you'}</span></span>
		</button>
		<button type="button" role="switch" class="sw" aria-checked={connection?.market_data_enabled ?? false} disabled={switching !== null || !connection} onclick={() => setMarket(!connection?.market_data_enabled)}>
			<span class="knob" aria-hidden="true"></span>
			<span class="sl"><b>Market figures</b><span>{connection?.market_data_enabled ? 'Replies may quote area prices' : 'Replies never quote prices'}</span></span>
		</button>
	</div>
</section>

<style>
.strip { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px 24px; padding: 14px 18px; border: 1px solid var(--sep); border-radius: 10px; background: var(--card); }
.line { display: flex; align-items: center; gap: 12px; min-width: 0; }
.dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.dot.live { background: var(--green); box-shadow: 0 0 0 4px var(--green-bg); }
.dot.idle { background: var(--text3); box-shadow: 0 0 0 4px var(--sunk); }
.id { display: grid; line-height: 1.3; min-width: 0; }
.id b { font-family: var(--font-display); font-size: 19px; font-weight: 560; letter-spacing: -.01em; font-variant-numeric: lining-nums tabular-nums; }
.id > span { font-size: 12.5px; color: var(--text3); }
.warn { color: var(--amber); }
.toggles { display: flex; flex-wrap: wrap; gap: 10px; }
.sw { display: flex; align-items: center; gap: 10px; padding: 8px 12px 8px 10px; border: 1px solid var(--sep); border-radius: 8px; text-align: left; background: var(--card); }
.sw:hover:not(:disabled) { border-color: var(--sep-strong); }
.sw:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.knob { position: relative; flex: none; width: 34px; height: 20px; border-radius: 999px; background: var(--sep-strong); transition: background .15s; }
.knob::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 1px 2px rgba(0,0,0,.2); transition: transform .15s; }
.sw[aria-checked='true'] .knob { background: var(--green); }
.sw[aria-checked='true'] .knob::after { transform: translateX(14px); }
.sl { display: grid; line-height: 1.3; }
.sl b { font-size: 13px; font-weight: 600; }
.sl span { font-size: 12px; color: var(--text3); }
@media (prefers-reduced-motion: reduce) { .knob, .knob::after { transition: none; } }
@media (max-width: 560px) { .strip { padding: 12px 14px; } .sw { flex: 1 1 100%; } }
</style>
