<script lang="ts">
/** Generated PDFs, newest first: one listing's (Documents tab) or the agency's (CRM › Documents). */
import { createQuery } from '@tanstack/svelte-query'
import type { GeneratedDocumentResponse } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '../../api'
import type { DocType } from '../../api/types'
import { fileSize } from '../../format'
import { crmQueries } from '../../queries'
import { toast } from '../../stores/toast.svelte'
import { errorText } from '../../write'
import Chip from '../ui/Chip.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import { docLabel } from './documentRules'

const PAGE = 50

let {
	listingKey,
	docType,
	search,
	showListing = false
}: { listingKey?: string; docType?: DocType; search?: string; showListing?: boolean } = $props()

let offset = $state(0)
// A new filter starts from the first page.
$effect(() => {
	void [listingKey, docType, search]
	offset = 0
})

const docs = createQuery(() =>
	crmQueries.documents({
		listingKey,
		docType,
		search: search?.trim() || undefined,
		limit: PAGE,
		offset
	})
)
let downloading = $state<string | null>(null)

const when = (iso: string) =>
	new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })

/** A fresh link for every click: links expire after a few minutes. */
async function download(d: GeneratedDocumentResponse) {
	downloading = d.id
	try {
		const link = await crm.documents.download(d.id)
		window.location.assign(link.url)
	} catch (e) {
		toast.show(errorText(e), { tone: 'error' })
	} finally {
		downloading = null
	}
}
</script>

<section class="sec">
	<h3>Generated documents{docs.data ? ` · ${docs.data.total}` : ''}</h3>
	{#if docs.isError}
		<ErrorLine message={errorText(docs.error)} onretry={() => docs.refetch()} />
	{:else if docs.data && !docs.data.items.length}
		<div class="small muted">{showListing ? 'No documents match.' : 'No PDFs generated for this listing yet.'}</div>
	{:else if docs.data}
		<div class="docs">
			{#each docs.data.items as d (d.id)}
				<div class="doc">
					<div>
						<div class="nm">{docLabel(d.doc_type)}</div>
						<div class="fn">
							{#if showListing}
								<a href="/crm/assets?listing=PF-{d.listing_key}&tab=documents">{d.listing_title}</a> ·
							{/if}
							{when(d.created_at)}{d.size_bytes ? ` · ${fileSize(d.size_bytes)}` : ''} · {d.template_version}
						</div>
					</div>
					<div class="acts">
						{#if d.status === 'ready'}
							<button
								type="button"
								class="btn ghost sm"
								disabled={downloading === d.id}
								onclick={() => download(d)}
							>
								{downloading === d.id ? 'Preparing…' : 'Download'}
							</button>
						{:else if d.status === 'failed'}
							<Chip tone="red">Failed</Chip>
						{:else}
							<Chip tone="amber">Generating</Chip>
						{/if}
					</div>
				</div>
			{/each}
		</div>
		{#if docs.data.total > PAGE}
			<div class="pager">
				<button type="button" class="btn ghost sm" disabled={offset === 0} onclick={() => (offset -= PAGE)}>Previous</button>
				<span class="small muted">{offset + 1}–{Math.min(offset + PAGE, docs.data.total)} of {docs.data.total}</span>
				<button
					type="button"
					class="btn ghost sm"
					disabled={offset + PAGE >= docs.data.total}
					onclick={() => (offset += PAGE)}>Next</button
				>
			</div>
		{/if}
	{:else}
		<div class="small muted">Loading documents…</div>
	{/if}
</section>

<style>
	.pager {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-top: 0.5rem;
	}
</style>
