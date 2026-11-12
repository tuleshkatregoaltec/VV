<script lang="ts">
/** Generated PDFs, newest first: one listing's (Documents tab) or the agency's (CRM › Documents). */
import { createQuery } from '@tanstack/svelte-query'
import type { GeneratedDocumentResponse } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '../../api'
import type { DocType } from '../../api/types'
import { fileSize, plural } from '../../format'
import { crmQueries } from '../../queries'
import { toast } from '../../stores/toast.svelte'
import { errorText } from '../../write'
import Chip from '../ui/Chip.svelte'
import ErrorLine from '../ui/ErrorLine.svelte'
import { docLabel, groupDocuments } from './documentRules'

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
let previewing = $state<string | null>(null)

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

/**
 * Open the PDF in a new tab. The tab opens on the click itself (so popup blockers allow it)
 * and is pointed at the fresh link once it arrives; it closes again if that fails.
 */
async function preview(d: GeneratedDocumentResponse) {
	const tab = window.open('', '_blank')
	if (tab) tab.opener = null
	previewing = d.id
	try {
		const link = await crm.documents.preview(d.id)
		if (tab) tab.location.href = link.url
		else window.location.assign(link.url)
	} catch (e) {
		tab?.close()
		toast.show(errorText(e), { tone: 'error' })
	} finally {
		previewing = null
	}
}
</script>

{#snippet row(d: GeneratedDocumentResponse)}
		<div class="doc">
			<div>
				<div class="nm">{docLabel(d.doc_type)}</div>
				<div class="fn">
					{when(d.created_at)}{d.size_bytes ? ` · ${fileSize(d.size_bytes)}` : ''} · {d.template_version}
				</div>
			</div>
			<div class="acts">
				{#if d.status === 'ready'}
					<button
						type="button"
						class="btn ghost sm"
						disabled={previewing === d.id}
						aria-label="Preview {docLabel(d.doc_type)}"
						onclick={() => preview(d)}
					>
						{previewing === d.id ? 'Opening…' : 'Preview'}
					</button>
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
{/snippet}

<section class="sec">
	<h3>Generated documents{docs.data ? ` · ${docs.data.total}` : ''}</h3>
	{#if docs.isError}
		<ErrorLine message={errorText(docs.error)} onretry={() => docs.refetch()} />
	{:else if docs.data && !docs.data.items.length}
		<div class="small muted">{showListing ? 'No documents match.' : 'No PDFs generated for this listing yet.'}</div>
	{:else if docs.data}
		{#if showListing}
			{#each groupDocuments(docs.data.items) as g (g.company)}
				{@const count = g.properties.reduce((n, p) => n + p.documents.length, 0)}
				<section class="company" aria-label={g.company}>
					<h4 class="company-name">
						{g.company}
						<span class="small muted">· {plural(g.properties.length, 'property', 'properties')} · {plural(count, 'document')}</span>
					</h4>
					{#each g.properties as p (p.listingKey)}
						<div class="property">
							<div class="property-head">
								<a href="/crm/assets?listing=PF-{p.listingKey}&tab=documents">{p.title}</a>
								<span class="small muted">{p.area ? `${p.area} · ` : ''}{plural(p.documents.length, 'document')}</span>
							</div>
							<div class="docs">
								{#each p.documents as d (d.id)}
									{@render row(d)}
								{/each}
							</div>
						</div>
					{/each}
				</section>
			{/each}
		{:else}
			<div class="docs">
				{#each docs.data.items as d (d.id)}
					{@render row(d)}
				{/each}
			</div>
		{/if}
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
	.company + .company {
		margin-top: 1.5rem;
	}
	.company-name {
		margin: 0.25rem 0 0.75rem;
		font-size: 1rem;
	}
	.property {
		margin: 0 0 1rem;
		padding-left: 0.75rem;
		border-left: 2px solid var(--line, rgba(127, 127, 127, 0.3));
	}
	.property-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		font-weight: 600;
	}
	.pager {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-top: 0.5rem;
	}
</style>
