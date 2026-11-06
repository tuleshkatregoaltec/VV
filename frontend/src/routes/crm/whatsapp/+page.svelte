<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { onDestroy } from 'svelte'
import { ApiError } from '$lib/api/client'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import AutomationCard from '$lib/components/whatsapp-connect/AutomationCard.svelte'
import ConnectCard from '$lib/components/whatsapp-connect/ConnectCard.svelte'
import ContactsCard from '$lib/components/whatsapp-connect/ContactsCard.svelte'
import GoodToKnow from '$lib/components/whatsapp-connect/GoodToKnow.svelte'
import StatusCard from '$lib/components/whatsapp-connect/StatusCard.svelte'
import StepRail from '$lib/components/whatsapp-connect/StepRail.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappConnectKeys, whatsappConnectQueries } from '$lib/queries/whatsapp-connect'
import { type ConnectPhase, stepStates } from '$lib/whatsapp/connect-state'
import { loadFacebookSdk } from '$lib/whatsapp/facebook-sdk'
import {
	createSignupCollector,
	describeCompleteError,
	type SignupResult
} from '$lib/whatsapp/signup'

// This page talks to the real API through $lib/api/client on purpose: it never goes through the
// CRM presentation layer, so it works the same with PUBLIC_CRM_PRESENTATION_MODE on.
const queryClient = getQueryClient()

const statusQuery = createQuery(() => whatsappConnectQueries.status())
const status = $derived(statusQuery.data ?? null)
const connected = $derived(status?.state === 'connected')

const configQuery = createQuery(() => ({
	...whatsappConnectQueries.config(),
	enabled: whatsappConnectQueries.config().enabled && statusQuery.isSuccess && !connected
}))
const config = $derived(configQuery.data)

type Sdk = Awaited<ReturnType<typeof loadFacebookSdk>>
let sdk = $state<Sdk | null>(null)
let sdkError = $state('')
let sdkAttempt = $state(0)
let phase = $state<ConnectPhase>('idle')
let signupError = $state('')
// The API answers 404 once nothing is connected, so remember the disconnect for this visit.
let disconnectedNote = $state<AgentConnectionStatus | null>(null)
let collector: ReturnType<typeof createSignupCollector> | null = null

$effect(() => {
	void sdkAttempt
	const cfg = config
	if (!cfg?.configured || !cfg.app_id || !cfg.config_id || connected) return
	let live = true
	loadFacebookSdk(cfg.app_id, cfg.graph_api_version).then(
		(fb) => {
			if (!live) return
			sdk = fb
			sdkError = ''
		},
		() => {
			if (live) sdkError = 'Meta’s sign-in script did not load.'
		}
	)
	return () => {
		live = false
	}
})

function retry() {
	sdkError = ''
	sdkAttempt += 1
	void configQuery.refetch()
}

async function finish(state: string, result: SignupResult) {
	phase = 'completing'
	try {
		const next = await whatsappConnect.complete({ state, ...result })
		disconnectedNote = null
		queryClient.setQueryData(whatsappConnectKeys.status(), next)
		await queryClient.invalidateQueries({ queryKey: whatsappConnectKeys.all })
		toast.show('WhatsApp connected. Your contacts are on their way.')
	} catch (e) {
		const code = e instanceof ApiError ? e.status : 0
		signupError = describeCompleteError(code)
		// The signed state token is single-attempt; get a fresh one for the next try.
		void configQuery.refetch()
		if (code === 409) void statusQuery.refetch()
	} finally {
		phase = 'idle'
		collector = null
	}
}

function connect() {
	const cfg = config
	if (!sdk || !cfg?.configured || !cfg.state || !cfg.config_id) return
	signupError = ''
	collector?.dispose()
	const state = cfg.state
	const mine = createSignupCollector({
		onComplete: (result) => void finish(state, result),
		onStop: (kind, message) => {
			signupError = message
			phase = 'idle'
			collector = null
			if (kind === 'timeout') void configQuery.refetch()
		}
	})
	collector = mine
	phase = 'waiting'
	// FB.login must run straight from the click, or browsers block the pop-up.
	sdk.login((response) => mine.handleLogin(response), {
		config_id: cfg.config_id,
		response_type: 'code',
		override_default_response_type: true,
		extras: cfg.extras
	})
}

function cancel() {
	collector?.dispose()
	collector = null
	phase = 'idle'
}

onDestroy(() => collector?.dispose())

const configMessage = $derived(
	configQuery.isError && !config ? 'Check your connection and try again.' : ''
)
const facts = $derived(
	connected
		? `Connected${status?.display_phone_number ? ` · ${status.display_phone_number}` : ''}`
		: 'Answer buyer enquiries from your own number'
)
</script>

<svelte:head><title>WhatsApp - Vitevue CRM</title></svelte:head>
<svelte:window onmessage={(event) => collector?.handleMessage(event)} />

<PageHeader title="WhatsApp" {facts} />

<div class="wa">
	<StepRail states={stepStates(status)} />

	{#if statusQuery.isError && !statusQuery.data}
		<div class="errline" role="alert">
			<span>Could not load your WhatsApp connection.</span>
			<button type="button" class="btn ghost sm" onclick={() => statusQuery.refetch()}>Retry</button>
		</div>
	{:else if !statusQuery.isSuccess}
		<div class="loading" aria-busy="true">Loading your WhatsApp connection…</div>
	{:else}
		<div class="cols">
			<div class="main">
				{#if status && connected}
					<StatusCard {status} ondisconnected={(next) => (disconnectedNote = next)} />
					<ContactsCard {status} />
					<AutomationCard {status} />
				{:else}
					<ConnectCard
						{config}
						configError={configMessage}
						sdkReady={sdk !== null}
						{sdkError}
						{phase}
						error={signupError}
						previous={status ?? disconnectedNote}
						onconnect={connect}
						oncancel={cancel}
						onretry={retry}
					/>
				{/if}
			</div>
			<aside class="side" aria-label="Good to know">
				<GoodToKnow {connected} />
			</aside>
		</div>
	{/if}
</div>

<style>
.wa { display: grid; gap: 22px; max-width: 1080px; }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 14px; align-items: start; }
.main { display: grid; gap: 14px; min-width: 0; }
.side { position: sticky; top: 0; }
.loading { padding: 40px 12px; text-align: center; color: var(--text3); font-size: 13.5px; }
@media (max-width: 960px) {
	.cols { grid-template-columns: minmax(0, 1fr); }
	.side { position: static; }
}
</style>
