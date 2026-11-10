<script lang="ts">
import { ApiError } from '$lib/api/client'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappConnectKeys } from '$lib/queries/whatsapp-connect'
import { automationView, contactsSyncPending } from '$lib/whatsapp/connect-state'

// A section of the connected card: the one switch that matters, and why replies may not be running.
let { status }: { status: AgentConnectionStatus } = $props()
const queryClient = getQueryClient()

let working = $state(false)
let skipWait = $state(false)

const view = $derived(automationView(status, status.state))
// The switch is the agent's own choice; `paused` is still switched on.
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

<section class="part" aria-labelledby="auto-h">
	<div class="head">
		<div class="title">
			<h2 id="auto-h">Automatic replies</h2>
			<span class={['chip', view.kind === 'on' ? 'green' : view.kind === 'paused' || view.kind === 'disconnected' ? 'amber' : 'outline']}>{view.label}</span>
		</div>
		<div class="actions">
			{#if on}
				<button type="button" class="btn ghost" disabled={working} onclick={() => set(false)}>Turn off replies</button>
			{:else}
				<button type="button" class="btn" disabled={working || waiting} onclick={() => set(true)}>Turn on replies</button>
			{/if}
		</div>
	</div>

	{#if view.note}
		<div class="note" role="status">
			<b>{view.note}</b>
			{#if view.resumeNote}<span>{view.resumeNote}</span>{/if}
		</div>
	{:else if on}
		<p>Property enquiries to <b>{status.display_phone_number ?? 'your number'}</b> are being answered automatically. Offers, negotiation, payments and viewings come back to you.</p>
	{:else}
		<p>
			Off. When on, property questions to your number are answered automatically{status.contacts.blocked > 0 ? `, except from the ${status.contacts.blocked} ${status.contacts.blocked === 1 ? 'contact' : 'contacts'} you blocked` : ''}.
			{#if waiting}
				<span class="hint">Contacts are still arriving. Wait so you can block personal ones first.</span>
				<button type="button" class="linkbtn" onclick={() => (skipWait = true)}>Turn on without waiting</button>
			{:else if status.contacts.blocked === 0}
				<span class="hint">You have not blocked anyone yet. Block personal contacts below first.</span>
			{/if}
		</p>
	{/if}

	<a class="more" href="/dashboard/whatsapp">What the assistant may say</a>
</section>

<style>
.part { display: grid; gap: 10px; padding: 18px 20px; border-top: 1px solid var(--sep); }
.head { display: flex; justify-content: space-between; align-items: center; gap: 10px 16px; flex-wrap: wrap; }
.title { display: flex; align-items: center; gap: 10px; }
h2 { margin: 0; font-size: 15.5px; font-weight: 600; letter-spacing: -.01em; }
p { margin: 0; font-size: 13.5px; line-height: 1.55; color: var(--text2); max-width: 62ch; }
p b { color: var(--text); font-weight: 600; }
.hint { display: block; margin-top: 4px; color: var(--text3); }
.linkbtn { font-size: 13.5px; }
.note { display: grid; gap: 4px; padding: 10px 12px; border-radius: 8px; border-left: 3px solid var(--amber); background: var(--amber-bg); font-size: 13.5px; line-height: 1.5; max-width: 62ch; }
.note b { font-weight: 600; color: var(--text); }
.note span { color: var(--text2); }
.more { justify-self: start; font-size: 12.5px; color: var(--accent); font-weight: 500; }
.more:hover { text-decoration: underline; }
</style>
