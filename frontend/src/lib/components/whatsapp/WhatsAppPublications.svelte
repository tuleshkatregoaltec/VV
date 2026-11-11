<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import type {
	ConnectionResponse,
	PublishedListingCreate,
	PublishedListingResponse
} from '$lib/api/generated/hey-api/types.gen'
import { whatsapp } from '$lib/api/whatsapp'
import { whatsappKeys, whatsappQueries } from '$lib/queries/whatsapp'

let { connection }: { connection: ConnectionResponse } = $props()
const queryClient = useQueryClient()
const listings = createQuery(() => whatsappQueries.listings(connection.id))
let busy = $state(false)
let error = $state<string | null>(null)
let editing = $state<PublishedListingResponse | null>(null)
let title = $state('')
let location = $state('')
let propertyType = $state<PublishedListingCreate['property_type']>('apartment')
let transaction = $state<PublishedListingCreate['transaction']>('sale')
let bedrooms = $state<number | undefined>(undefined)
let price = $state<number | undefined>(undefined)
let area = $state<number | undefined>(undefined)
let availability = $state<PublishedListingCreate['availability']>('available')
let expires = $state('')
let approved = $state(false)

function localDate(value: Date): string {
	return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

function reset() {
	editing = null
	title = ''
	location = ''
	propertyType = 'apartment'
	transaction = 'sale'
	bedrooms = undefined
	price = undefined
	area = undefined
	availability = 'available'
	expires = ''
	approved = false
}

function edit(listing: PublishedListingResponse) {
	editing = listing
	title = listing.title
	location = listing.location
	propertyType = listing.property_type
	transaction = listing.transaction
	bedrooms = listing.bedrooms ?? undefined
	price = listing.price_aed
	area = listing.area_sqft ?? undefined
	availability = listing.availability
	expires = localDate(new Date(Date.now() + 24 * 60 * 60 * 1000))
	approved = false
}

async function run(operation: () => Promise<unknown>) {
	if (busy) return
	busy = true
	error = null
	try {
		await operation()
	} catch (cause) {
		error = cause instanceof Error ? cause.message : 'The publication could not be saved.'
	} finally {
		await queryClient.invalidateQueries({ queryKey: whatsappKeys.all })
		busy = false
	}
}

async function publish(event: SubmitEvent) {
	event.preventDefault()
	const expiry = new Date(expires)
	if (!approved || !price || !Number.isFinite(expiry.getTime())) return
	const body: PublishedListingCreate = {
		title,
		location,
		property_type: propertyType,
		transaction,
		bedrooms: bedrooms ?? null,
		price_aed: price,
		area_sqft: area ?? null,
		availability,
		expires_at: expiry.toISOString(),
		approved_for_customer: true
	}
	await run(async () => {
		if (editing) {
			await whatsapp.updateListing(connection.id, editing.id, {
				...body,
				expected_revision: editing.revision
			})
		} else {
			await whatsapp.publishListing(connection.id, body)
		}
		reset()
	})
}
</script>

<section class="mt-4 rounded-lg border border-border bg-card p-4" aria-label="Customer information">
	<h2 class="font-semibold">Customer information</h2>
	<p class="mt-1 text-sm text-fg-3">Customers can receive approved listing details and permitted market summaries. Your private CRM stays private.</p>
	<label class="mt-4 flex items-start gap-3 text-sm">
		<input type="checkbox" class="mt-1" checked={connection.market_data_enabled} disabled={busy} onchange={(event) => run(() => whatsapp.updateConnection(connection.id, { market_data_enabled: event.currentTarget.checked }))} />
		<span>I have permission to share this number’s market summaries with customers.</span>
	</label>
	{#if error}<p class="mt-3 text-sm text-error" role="alert">{error}</p>{/if}
	{#if listings.isError}<p class="mt-3 text-sm text-error" role="alert">Could not load published listings. Refresh before making changes.</p>{/if}
	<h3 class="mt-5 font-medium">Published listings</h3>
	{#if listings.isPending}<p class="mt-2 text-sm text-fg-3">Loading listings…</p>
	{:else if !listings.isError && !listings.data?.length}<p class="mt-2 text-sm text-fg-3">No listings published for this number.</p>{/if}
	<ul class="mt-2 space-y-3">
		{#each listings.data ?? [] as listing (listing.id)}
			<li class="flex flex-wrap items-start justify-between gap-3 border-t border-border pt-3">
				<div class="min-w-0">
					<p class="break-words text-sm font-medium">{listing.title}</p>
					<p class="text-sm text-fg-3">{listing.location} · AED {listing.price_aed.toLocaleString('en-AE')}{listing.transaction === 'rent' ? ' per year' : ''}</p>
					<p class="mt-1 text-xs text-fg-3">{listing.revoked_at ? 'Revoked' : new Date(listing.expires_at) <= new Date() ? 'Expired' : listing.availability === 'available' ? 'Published' : listing.availability === 'under_offer' ? 'Under offer' : 'Unavailable'} · Expires {new Date(listing.expires_at).toLocaleString()}</p>
				</div>
				<div class="flex gap-2">
					<button type="button" class="ui-button px-3 py-2 text-sm" disabled={busy || listings.isError} onclick={() => edit(listing)}>Edit and renew</button>
					<button type="button" class="ui-button px-3 py-2 text-sm" disabled={busy || listings.isError || !!listing.revoked_at} onclick={() => run(() => whatsapp.revokeListing(connection.id, listing.id, listing.revision))}>Revoke</button>
				</div>
			</li>
		{/each}
	</ul>
	<form class="mt-5 border-t border-border pt-4" onsubmit={publish}>
		<h3 class="font-medium">{editing ? 'Approve updated listing details' : 'Publish a listing'}</h3>
		<p class="mt-1 text-xs text-fg-3">Enter customer-facing information only. Verify the price and availability before approving. Publications expire within 30 days.</p>
		<div class="mt-3 grid gap-3 sm:grid-cols-2">
			<label class="grid gap-1 text-sm">Listing title<input class="rounded-md border border-border bg-app p-2" bind:value={title} required maxlength="120" disabled={busy} /></label>
			<label class="grid gap-1 text-sm">Location<input class="rounded-md border border-border bg-app p-2" bind:value={location} required maxlength="120" disabled={busy} /></label>
			<label class="grid gap-1 text-sm">Property type<select class="rounded-md border border-border bg-app p-2" bind:value={propertyType} disabled={busy}>{#each ['apartment', 'villa', 'townhouse', 'penthouse', 'office', 'land', 'other'] as kind}<option value={kind}>{kind}</option>{/each}</select></label>
			<label class="grid gap-1 text-sm">Transaction<select class="rounded-md border border-border bg-app p-2" bind:value={transaction} disabled={busy}><option value="sale">Sale</option><option value="rent">Rent</option></select></label>
			<label class="grid gap-1 text-sm">Bedrooms (optional)<input type="number" min="0" max="20" step="1" class="rounded-md border border-border bg-app p-2" bind:value={bedrooms} disabled={busy} /></label>
			<label class="grid gap-1 text-sm">{transaction === 'rent' ? 'Annual rent (AED)' : 'Asking price (AED)'}<input type="number" min="0.01" step="0.01" class="rounded-md border border-border bg-app p-2" bind:value={price} required disabled={busy} /></label>
			<label class="grid gap-1 text-sm">Size in sq ft (optional)<input type="number" min="0.01" step="0.01" class="rounded-md border border-border bg-app p-2" bind:value={area} disabled={busy} /></label>
			<label class="grid gap-1 text-sm">Availability<select class="rounded-md border border-border bg-app p-2" bind:value={availability} disabled={busy}><option value="available">Available</option><option value="under_offer">Under offer</option><option value="unavailable">Unavailable</option></select></label>
			<label class="grid gap-1 text-sm">Approval expires (your local time)<input type="datetime-local" class="rounded-md border border-border bg-app p-2" bind:value={expires} required disabled={busy} /></label>
		</div>
		<label class="mt-4 flex items-start gap-3 text-sm"><input type="checkbox" class="mt-1" bind:checked={approved} required disabled={busy} /><span>I have verified these details and approve sharing them with customers.</span></label>
		<div class="mt-4 flex gap-2">
			<button type="submit" class="ui-button px-3 py-2 text-sm" disabled={busy || listings.isError || !approved}>{busy ? 'Saving…' : editing ? 'Publish approved update' : 'Publish approved listing'}</button>
			{#if editing}<button type="button" class="ui-button px-3 py-2 text-sm" disabled={busy} onclick={reset}>Cancel edit</button>{/if}
		</div>
	</form>
</section>
