<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { onDestroy } from 'svelte'
import { goto } from '$app/navigation'
import { page } from '$app/state'
import { ApiError } from '$lib/api/client'
import { type AgentConnectionStatus, whatsappConnect } from '$lib/api/whatsapp-connect'
import WhatsAppPublications from '$lib/components/whatsapp/WhatsAppPublications.svelte'
import AutomationCard from '$lib/components/whatsapp-connect/AutomationCard.svelte'
import ChatMirror from '$lib/components/whatsapp-connect/ChatMirror.svelte'
import ConnectCard from '$lib/components/whatsapp-connect/ConnectCard.svelte'
import ContactsCard from '$lib/components/whatsapp-connect/ContactsCard.svelte'
import GoodToKnow from '$lib/components/whatsapp-connect/GoodToKnow.svelte'
import StatusCard from '$lib/components/whatsapp-connect/StatusCard.svelte'
import StatusStrip from '$lib/components/whatsapp-connect/StatusStrip.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import { whatsappKeys, whatsappQueries } from '$lib/queries/whatsapp'
import { whatsappConnectKeys, whatsappConnectQueries } from '$lib/queries/whatsapp-connect'
import type { ConnectPhase } from '$lib/whatsapp/connect-state'
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

// Once connected, the page is a workspace: live chats, the block list, what the assistant may
// share, and the connection itself. The tab lives in the URL so other pages can link to it.
const TABS = [
	{ id: 'chats', label: 'Conversations' },
	{ id: 'block', label: 'Block list' },
	{ id: 'listings', label: 'Listings' },
	{ id: 'connection', label: 'Connection' }
] as const
type Tab = (typeof TABS)[number]['id']
const tab = $derived<Tab>(
	(TABS.find((t) => t.id === page.url.searchParams.get('tab'))?.id ?? 'chats') as Tab
)
function choose(next: Tab) {
	const url = new URL(page.url)
	if (next === 'chats') url.searchParams.delete('tab')
	else url.searchParams.set('tab', next)
	void goto(url, { replaceState: true, noScroll: true, keepFocus: true })
}

const notifications = createQuery(() => ({
	...whatsappQueries.notifications(),
	enabled: connected
}))
const waiting = $derived(
	(notifications.data ?? []).filter((m) => m.status === 'approval_required').length
)
const connections = createQuery(() => ({ ...whatsappQueries.connections(), enabled: connected }))
const connection = $derived(
	connections.data?.find((c) => c.id === status?.connection_id) ?? connections.data?.[0] ?? null
)

const configMessage = $derived(
	configQuery.isError && !config ? 'Check your connection and try again.' : ''
)
const facts = 'Answer buyer enquiries from your own number'
</script>

<svelte:head><title>WhatsApp - Vitevue CRM</title></svelte:head>
<svelte:window onmessage={(event) => collector?.handleMessage(event)} />

<PageHeader title="WhatsApp" {facts} />

<div class={['wa', connected && 'wide']}>
	{#if statusQuery.isError && !statusQuery.data}
		<div class="errline" role="alert">
			<span>Could not load your WhatsApp connection.</span>
			<button type="button" class="btn ghost sm" onclick={() => statusQuery.refetch()}>Retry</button>
		</div>
	{:else if !statusQuery.isSuccess}
		<div class="loading" aria-busy="true">Loading your WhatsApp connection…</div>
	{:else if status && connected}
		<StatusStrip {status} {connection} />

		<div class="tabs" role="tablist" aria-label="WhatsApp sections">
			{#each TABS as t (t.id)}
				<button type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls="wa-panel" onclick={() => choose(t.id)}>
					{t.label}
					{#if t.id === 'chats' && waiting > 0}<span class="badge" aria-label={`${waiting} waiting for approval`}>{waiting}</span>{/if}
					{#if t.id === 'block'}<span class="n">{status.contacts.blocked}</span>{/if}
				</button>
			{/each}
		</div>

		<div id="wa-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} class="panel">
			{#if tab === 'chats'}
				{#if status.connection_id}<ChatMirror connectionId={status.connection_id} />{/if}
			{:else if tab === 'block'}
				<ContactsCard {status} />
			{:else if tab === 'listings'}
				<div class="card pad">
					{#if connection}{#key connection.id}<WhatsAppPublications {connection} />{/key}
					{:else if connections.isError}<p class="quiet">Could not load listings. Refresh the page.</p>
					{:else}<p class="quiet">Loading listings…</p>{/if}
				</div>
			{:else}
				<div class="card">
					<StatusCard {status} ondisconnected={(next) => (disconnectedNote = next)} />
					<AutomationCard {status} />
				</div>
				<GoodToKnow connected />
			{/if}
		</div>
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
		<GoodToKnow />
	{/if}
</div>

<style>
.wa { display: grid; gap: 14px; max-width: 720px; }
.wa.wide { max-width: 1240px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--sep); overflow-x: auto; scrollbar-width: none; }
.tabs button { display: inline-flex; align-items: center; gap: 6px; padding: 9px 12px; margin-bottom: -1px; border-bottom: 2px solid transparent; font-size: 13.5px; font-weight: 500; color: var(--text2); white-space: nowrap; }
.tabs button:hover { color: var(--text); }
.tabs button[aria-selected='true'] { color: var(--text); border-bottom-color: var(--accent-fill); font-weight: 600; }
.tabs button:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: 4px; }
.badge { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px; background: var(--amber); color: #fff; font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
.n { font-size: 12px; color: var(--text3); font-variant-numeric: tabular-nums; }
.panel { display: grid; gap: 14px; min-width: 0; }
.pad { padding: 18px 20px; }
.quiet { margin: 0; color: var(--text3); font-size: 13.5px; }

.loading { padding: 40px 12px; text-align: center; color: var(--text3); font-size: 13.5px; }
</style>
