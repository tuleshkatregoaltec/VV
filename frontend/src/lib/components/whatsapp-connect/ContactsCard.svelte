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
import { formatPhone } from '$lib/whatsapp/chat'
import { contactsSyncPending } from '$lib/whatsapp/connect-state'
import BlockFromFile from './BlockFromFile.svelte'

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
	return contact.name?.trim() || formatPhone(contact.wa_id)
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
		<h2 id="contacts-h">Block list <span class="ct">{status.contacts.blocked} blocked</span></h2>
	</div>
	<div class="stack">
		<p class="lead">Messages from blocked contacts are never read or stored. Everyone else is treated as a possible enquiry.</p>

		{#if pending}
			<div class="sync" role="status">
				<span class="spin" aria-hidden="true"></span>
				<span class="sync-text"><b>Syncing your contacts from WhatsApp</b> This takes a few minutes and updates by itself.</span>
				<button type="button" class="btn ghost sm" onclick={retrySync} disabled={syncing}>{syncing ? 'Asking…' : 'Ask again'}</button>
			</div>
		{/if}

		<div class="filters">
			<label class="search">
				<Search size={14} aria-hidden="true" />
				<input type="search" bind:value={searchInput} placeholder="Search contacts" aria-label="Search contacts" />
			</label>
			<div class="seg" role="group" aria-label="Show contacts">
				<button type="button" aria-pressed={view === 'all'} onclick={() => (view = 'all')}>All</button>
				<button type="button" aria-pressed={view === 'blocked'} onclick={() => (view = 'blocked')}>Blocked</button>
			</div>
		</div>

		{#if query.isError && rows.length === 0}
			<div class="errline" role="alert"><span>Could not load your contacts.</span><button type="button" class="btn ghost sm" onclick={() => query.refetch()}>Retry</button></div>
		{:else if query.isPending}
			<div class="quiet" aria-busy="true">Loading contacts…</div>
		{:else if rows.length === 0}
			<div class="quiet">
				{#if search}No contacts match “{search}”. You can still block that number below.
				{:else if view === 'blocked'}You have not blocked anyone yet.
				{:else if pending}Contacts will appear here as they arrive.
				{:else}Nobody is on your block list yet. Import your phone’s contacts or type numbers below.{/if}
			</div>
		{:else}
			<div class="listbox">
				<div class="lh">
					<label class="all"><input type="checkbox" checked={allShown} onchange={() => (selected = selectVisible(selected, rows))} /> Select all shown</label>
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
					{:else}
						<span class="count" aria-live="polite">{total} {total === 1 ? 'contact' : 'contacts'}</span>
					{/if}
				</div>
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
								{#if contact.name || contact.in_address_book}
									<span class="sub">{#if contact.name}<span class="num">{formatPhone(contact.wa_id)}</span>{/if}{#if contact.name && contact.in_address_book}{' · '}{/if}{#if contact.in_address_book}Saved{/if}</span>
								{/if}
							</div>
							{#if contact.blocked}<span class="chip red">Blocked</span>{/if}
							<button
								type="button"
								class="btn ghost sm"
								disabled={working}
								onclick={() => apply(!contact.blocked, new Set([contact.id]))}
								aria-label="{contact.blocked ? 'Unblock' : 'Block'} {label(contact)}"
							>{contact.blocked ? 'Unblock' : 'Block'}</button>
						</li>
					{/each}
				</ul>
				{#if query.hasNextPage}
					<button type="button" class="more" disabled={query.isFetchingNextPage} onclick={() => query.fetchNextPage()}>
						{query.isFetchingNextPage ? 'Loading…' : `Show more (${total - rows.length} left)`}
					</button>
				{/if}
			</div>
		{/if}

		<BlockFromFile {working} onblock={(numbers) => apply(true, new Set(), numbers)} />

		<form class="add" onsubmit={blockNumbers}>
			<label class="sr" for="wa-block-number">Block a number that is not in the list</label>
			<div class="addrow">
				<input id="wa-block-number" type="text" inputmode="tel" bind:value={numberText} placeholder="Type a number, e.g. +971 50 123 4567" aria-describedby={numberError ? 'wa-block-error' : 'wa-block-help'} aria-invalid={numberError ? 'true' : undefined} />
				<button type="submit" class="btn ghost" disabled={working || !numberText.trim()}>Block number</button>
			</div>
			{#if numberError}<span id="wa-block-error" class="err" role="alert">{numberError}</span>{/if}
			<span id="wa-block-help" class="help">Separate several numbers with commas or new lines.</span>
		</form>
	</div>
</section>

<style>
.ch { padding: 14px 20px; }
.stack { display: grid; gap: 14px; padding: 16px 20px 20px; }
.lead { margin: 0; font-size: 13.5px; line-height: 1.55; color: var(--text2); max-width: 62ch; }
.sync { display: flex; gap: 10px; align-items: center; background: var(--blue-bg); border-radius: 8px; padding: 8px 12px; font-size: 13px; color: var(--text2); }
.sync-text { flex: 1; min-width: 0; }
.sync b { color: var(--blue); font-weight: 600; margin-right: 4px; }
.spin { flex: none; width: 14px; height: 14px; border-radius: 50%; border: 2px solid var(--blue); border-right-color: transparent; animation: turn .9s linear infinite; }
@keyframes turn { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .spin { animation: none; border-right-color: var(--blue); } }
.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.search { flex: 1 1 200px; }
.quiet { padding: 28px 12px; text-align: center; color: var(--text3); font-size: 13.5px; }
.listbox { border: 1px solid var(--sep); border-radius: 8px; overflow: hidden; }
.lh { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 8px; min-height: 40px; padding: 6px 12px; background: var(--sunk); border-bottom: 1px solid var(--sep); font-size: 12.5px; color: var(--text2); }
.bulk { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; justify-content: flex-end; color: var(--text); font-size: 13px; }
.bulk b { margin-right: 4px; }
.all { display: flex; gap: 8px; align-items: center; }
.count { font-variant-numeric: tabular-nums; }
.list { list-style: none; margin: 0; padding: 0; max-height: 400px; overflow: auto; }
.row { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 8px 12px; border-bottom: 1px solid var(--sep); }
.row:last-child { border-bottom: 0; }
.row.is-blocked { background: var(--sunk); }
.who { display: grid; min-width: 0; line-height: 1.35; }
.who b { font-weight: 550; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sub { font-size: 12.5px; color: var(--text3); }
.num { font-variant-numeric: tabular-nums; }
.more { display: block; width: 100%; padding: 9px; border-top: 1px solid var(--sep); font-size: 13px; font-weight: 500; color: var(--accent); }
.more:hover:not(:disabled) { background: var(--hover); }
.add { display: grid; gap: 6px; }
.addrow { display: flex; gap: 8px; flex-wrap: wrap; }
.addrow input { flex: 1 1 240px; }
.help { font-size: 12px; color: var(--text3); }
.err { color: var(--red); font-size: 12.5px; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
@media (max-width: 560px) {
	.ch { padding: 12px 14px; }
	.stack { padding: 14px; }
	.row { grid-template-columns: 18px minmax(0, 1fr) auto; }
	.row .chip { display: none; }
}
</style>
