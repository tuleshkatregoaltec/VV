<script lang="ts">
import { ApiError } from '$lib/api/client'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappConnectKeys } from '$lib/queries/whatsapp-connect'
import { contactsSyncPending } from '$lib/whatsapp/connect-state'

let { status }: { status: AgentConnectionStatus } = $props()
const queryClient = getQueryClient()

let working = $state(false)
let skipWait = $state(false)

const on = $derived(status.automation_enabled)
const waiting = $derived(!on && contactsSyncPending(status) && !skipWait)

async function set(enabled: boolean) {
	working = true
	try {
		const next = await whatsappConnect.setAutomation(enabled)
		queryClient.setQueryData(whatsappConnectKeys.status(), next)
		toast.show(enabled ? 'Automatic replies are on.' : 'Automatic replies are off.')
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.status === 409
				? 'Vitevue’s access to your WhatsApp has expired. Disconnect and connect again.'
				: e instanceof ApiError && e.message
					? e.message
					: 'Could not change automatic replies. Try again.',
			{ tone: 'error' }
		)
	} finally {
		working = false
	}
}
</script>

<section class="card" aria-labelledby="auto-h">
	<div class="ch">
		<h2 id="auto-h">Turn on replies</h2>
		<span class={['chip', on ? 'green' : 'outline']}>{on ? 'On' : 'Off'}</span>
	</div>
	<div class="cb stack">
		{#if on}
			<p>Property enquiries to <b>{status.display_phone_number ?? 'your number'}</b> are being answered automatically. Offers, negotiation, payments and viewings come back to you.</p>
		{:else}
			<p>Replies start <b>off</b>. Once they are on, real estate questions sent to your number are answered automatically, except from the {status.contacts.blocked} {status.contacts.blocked === 1 ? 'contact' : 'contacts'} you blocked.</p>
			{#if status.contacts.blocked === 0}
				<p class="muted">You have not blocked anyone yet. Block personal contacts first so Vitevue never reads their messages.</p>
			{/if}
			{#if waiting}
				<p class="muted">Contacts are still arriving. Wait so you can block personal ones first.</p>
			{/if}
		{/if}
		<div class="row">
			{#if on}
				<button type="button" class="btn ghost" disabled={working} onclick={() => set(false)}>Turn off replies</button>
			{:else}
				<button type="button" class="btn" disabled={working || waiting} onclick={() => set(true)}>Turn on replies</button>
				{#if waiting}
					<button type="button" class="btn plain" onclick={() => (skipWait = true)}>Turn on without waiting</button>
				{/if}
			{/if}
			<a class="btn plain" href="/dashboard/whatsapp">What the assistant may say</a>
		</div>
	</div>
</section>

<style>
.stack { display: grid; gap: 12px; padding: 16px; }
p { margin: 0; font-size: 14px; line-height: 1.55; color: var(--text2); max-width: 62ch; }
p b { color: var(--text); }
.row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
</style>
