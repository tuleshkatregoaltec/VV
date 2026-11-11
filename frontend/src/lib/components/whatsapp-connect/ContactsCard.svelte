<script lang="ts">
import { createInfiniteQuery } from '@tanstack/svelte-query'
import Search from 'lucide-svelte/icons/search'
import { ApiError } from '$lib/api/client'
import {
	type AgentConnectionStatus,
	type SyncedContact,
	whatsappConnect
} from '$lib/api/whatsapp-connect'
import { toast } from '$lib/crm/stores/toast.svelte'
import { getQueryClient } from '$lib/queries/client'
import {
	SYNC_POLL_MS,
	whatsappConnectKeys,
	whatsappConnectQueries
} from '$lib/queries/whatsapp-connect'
import {
	buildBlockRequest,
	parsePhoneNumbers,
	selectionAfterToggle,
	selectVisible
} from '$lib/whatsapp/blocklist'
import { contactsSyncPending } from '$lib/whatsapp/connect-state'

let { status }: { status: AgentConnectionStatus } = $props()
const queryClient = getQueryClient()

let searchInput = $state('')
let search = $state('')
let view = $state<'all' | 'blocked'>('all')
let selected = $state<Set<string>>(new Set())
let numberText = $state('')
let numberError = $state('')
let working = $state(false)
let syncing = $state(false)

$effect(() => {
	const next = searchInput.trim()
	const timer = setTimeout(() => (search = next), 250)
	return () => clearTimeout(timer)
})

const pending = $derived(contactsSyncPending(status))
const query = createInfiniteQuery(() =>
	whatsappConnectQueries.contacts(search, view === 'blocked', true, pending ? SYNC_POLL_MS : false)
)
const rows = $derived<SyncedContact[]>(query.data?.pages.flatMap((page) => page.items) ?? [])
const total = $derived(query.data?.pages.at(-1)?.total ?? 0)
const allShown = $derived(rows.length > 0 && rows.every((row) => selected.has(row.id)))
const chosen = $derived(rows.filter((row) => selected.has(row.id)))
const toBlock = $derived(chosen.filter((row) => !row.blocked))
const toUnblock = $derived(chosen.filter((row) => row.blocked))

function label(contact: SyncedContact) {
	return contact.name?.trim() || `+${contact.wa_id}`
}

async function apply(blocked: boolean, ids: ReadonlySet<string>, numbers: string[] = []) {
	const requests = buildBlockRequest({ ids, numbers, blocked })
	if (requests.length === 0) return false
	working = true
	try {
		let updated = 0
		for (const request of requests) updated += (await whatsappConnect.setBlocked(request)).updated
		selected = new Set()
		await Promise.all([queryClient.invalidateQueries({ queryKey: whatsappConnectKeys.all })])
		toast.show(
			blocked
				? `Blocked ${updated} ${updated === 1 ? 'contact' : 'contacts'}. Vitevue will not read their messages.`
				: `Unblocked ${updated} ${updated === 1 ? 'contact' : 'contacts'}.`
		)
		return true
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.message
				? e.message
				: 'Could not update your block list. Try again.',
			{ tone: 'error' }
		)
		return false
	} finally {
		working = false
	}
}

async function blockNumbers(event: SubmitEvent) {
	event.preventDefault()
	const { numbers, invalid } = parsePhoneNumbers(numberText)
	if (invalid.length > 0) {
		numberError = `Check ${invalid.length === 1 ? 'this entry' : 'these entries'}: ${invalid.join(', ')}. Use the full number with country code, for example +971 50 123 4567.`
		return
	}
	if (numbers.length === 0) {
		numberError = 'Enter at least one phone number.'
		return
	}
	numberError = ''
	if (await apply(true, new Set(), numbers)) numberText = ''
}

async function retrySync() {
	syncing = true
	try {
		const next = await whatsappConnect.retrySync()
		queryClient.setQueryData(whatsappConnectKeys.status(), next)
		toast.show('Asked WhatsApp to send your contacts again. This takes a few minutes.')
	} catch (e) {
		toast.show(
			e instanceof ApiError && e.status === 409
				? 'Contacts can only be requested once, within 24 hours of connecting. If none arrived, add numbers below to block them.'
				: e instanceof ApiError && e.message
					? e.message
					: 'Could not request contacts. Try again.',
			{ tone: 'error' }
		)
	} finally {
		syncing = false
	}
}
</script>

<section class="card" aria-labelledby="contacts-h">
	<div class="ch">
		<h2 id="contacts-h">Choose who to block <span class="ct">{status.contacts.blocked} blocked</span></h2>
	</div>
	<div class="cb stack">
		<p class="lead">Block family, friends and anyone personal. Vitevue never reads messages from blocked contacts. Everyone else is treated as a possible enquiry.</p>

		{#if pending}
			<div class="sync" role="status">
				<span class="spin" aria-hidden="true"></span>
				<div>
					<b>Syncing your contacts from WhatsApp</b>
					<span>This takes a few minutes. This page updates by itself, and you can add numbers to block below while you wait.</span>
				</div>
				<button type="button" class="btn ghost sm" onclick={retrySync} disabled={syncing}>{syncing ? 'Asking…' : 'Ask again'}</button>
			</div>
		{/if}

		<div class="filters">
			<label class="search">
				<Search size={14} aria-hidden="true" />
				<input type="search" bind:value={searchInput} placeholder="Search name or number" aria-label="Search contacts" />
			</label>
			<div class="seg" role="group" aria-label="Show contacts">
				<button type="button" aria-pressed={view === 'all'} onclick={() => (view = 'all')}>All</button>
				<button type="button" aria-pressed={view === 'blocked'} onclick={() => (view = 'blocked')}>Blocked</button>
			</div>
			<span class="count" aria-live="polite">{total} {total === 1 ? 'contact' : 'contacts'}</span>
		</div>

		{#if chosen.length > 0}
			<div class="bulk" role="region" aria-label="Selected contacts">
				<b>{chosen.length} selected</b>
				{#if toBlock.length > 0}
					<button type="button" class="btn sm" disabled={working} onclick={() => apply(true, new Set(toBlock.map((r) => r.id)))}>Block {toBlock.length}</button>
				{/if}
				{#if toUnblock.length > 0}
					<button type="button" class="btn ghost sm" disabled={working} onclick={() => apply(false, new Set(toUnblock.map((r) => r.id)))}>Unblock {toUnblock.length}</button>
				{/if}
				<button type="button" class="btn plain sm" onclick={() => (selected = new Set())}>Clear</button>
			</div>
		{/if}

		{#if query.isError && rows.length === 0}
			<div class="errline" role="alert"><span>Could not load your contacts.</span><button type="button" class="btn ghost sm" onclick={() => query.refetch()}>Retry</button></div>
		{:else if query.isPending}
			<div class="quiet" aria-busy="true">Loading contacts…</div>
		{:else if rows.length === 0}
			<div class="quiet">
				{#if search}No contacts match “{search}”. You can still block that number below.
				{:else if view === 'blocked'}You have not blocked anyone yet.
				{:else if pending}Contacts will appear here as they arrive.
				{:else}No contacts were synced from WhatsApp. Add numbers to block below.{/if}
			</div>
		{:else}
			<label class="all"><input type="checkbox" checked={allShown} onchange={() => (selected = selectVisible(selected, rows))} /> Select all shown</label>
			<ul class="list">
				{#each rows as contact (contact.id)}
					<li class={['row', contact.blocked && 'is-blocked']}>
						<input
							type="checkbox"
							checked={selected.has(contact.id)}
							onchange={() => (selected = selectionAfterToggle(selected, contact.id))}
							aria-label="Select {label(contact)}"
						/>
						<div class="who">
							<b>{label(contact)}</b>
							{#if contact.name}<span class="muted num">+{contact.wa_id}</span>{/if}
						</div>
						{#if contact.in_address_book}<span class="chip outline">Saved</span>{/if}
						{#if contact.blocked}<span class="chip red">Blocked</span>{/if}
						<button
							type="button"
							class={['btn sm', contact.blocked ? 'ghost' : 'danger']}
							disabled={working}
							onclick={() => apply(!contact.blocked, new Set([contact.id]))}
							aria-label="{contact.blocked ? 'Unblock' : 'Block'} {label(contact)}"
						>{contact.blocked ? 'Unblock' : 'Block'}</button>
					</li>
				{/each}
			</ul>
			{#if query.hasNextPage}
				<button type="button" class="btn ghost more" disabled={query.isFetchingNextPage} onclick={() => query.fetchNextPage()}>
					{query.isFetchingNextPage ? 'Loading…' : `Show more (${total - rows.length} left)`}
				</button>
			{/if}
		{/if}

		<form class="add" onsubmit={blockNumbers}>
			<div class="fld">
				<label for="wa-block-number">Block a number that is not in the list</label>
				<div class="addrow">
					<input id="wa-block-number" type="text" inputmode="tel" bind:value={numberText} placeholder="+971 50 123 4567" aria-describedby={numberError ? 'wa-block-error' : undefined} aria-invalid={numberError ? 'true' : undefined} />
					<button type="submit" class="btn ghost" disabled={working || !numberText.trim()}>Block number</button>
				</div>
				{#if numberError}<span id="wa-block-error" class="err" role="alert">{numberError}</span>{/if}
				<span class="muted help">Separate several numbers with commas or new lines.</span>
			</div>
		</form>
	</div>
</section>

<style>
.stack { display: grid; gap: 14px; padding: 16px; }
.lead { margin: 0; font-size: 14px; line-height: 1.55; color: var(--text2); max-width: 62ch; }
.sync { display: flex; gap: 12px; align-items: center; background: var(--blue-bg); border-radius: 8px; padding: 10px 12px; font-size: 13.5px; }
.sync > div { display: grid; gap: 2px; flex: 1; min-width: 0; }
.sync b { color: var(--blue); font-weight: 600; }
.sync span:not(.spin) { color: var(--text2); }
.spin { flex: none; width: 16px; height: 16px; border-radius: 50%; border: 2px solid var(--blue); border-right-color: transparent; animation: turn .9s linear infinite; }
@keyframes turn { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; border-right-color: var(--blue); } }
.bulk { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 10px; border-radius: 8px; background: var(--sel); font-size: 13.5px; }
.bulk b { margin-right: auto; }
.quiet { padding: 28px 12px; text-align: center; color: var(--text3); font-size: 13.5px; }
.all { display: flex; gap: 8px; align-items: center; font-size: 12.5px; color: var(--text2); padding: 0 12px; }
.list { list-style: none; margin: 0; padding: 0; border: 1px solid var(--sep); border-radius: 8px; max-height: 440px; overflow: auto; }
.row { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto auto auto; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--sep); }
.row:last-child { border-bottom: 0; }
.row.is-blocked { background: var(--sunk); }
.who { display: grid; min-width: 0; line-height: 1.3; }
.who b { font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.num { font-size: 12.5px; font-variant-numeric: tabular-nums; }
.more { justify-self: center; }
.add { border-top: 1px solid var(--sep); padding-top: 14px; }
.addrow { display: flex; gap: 8px; flex-wrap: wrap; }
.addrow input { flex: 1 1 220px; max-width: 320px; }
.help { font-size: 12px; }
.err { color: var(--red); font-size: 12.5px; }
@media (max-width: 560px) {
	.row { grid-template-columns: 18px minmax(0, 1fr) auto; }
	.row .chip { display: none; }
}
</style>
