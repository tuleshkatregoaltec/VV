<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { Download, Loader2 } from 'lucide-svelte'
import { type BrokerActionResponse, broker } from '$lib/api/broker'
import type { BrokerActionArtifact, BrokerDocumentArtifact } from '$lib/chat/artifacts'
import { brokerQueries } from '$lib/queries/broker'
import { getQueryClient } from '$lib/queries/client'
import { inboundKeys } from '$lib/queries/inbound'

let { artifact }: { artifact: BrokerDocumentArtifact | BrokerActionArtifact } = $props()
let confirmation = $state<BrokerActionResponse | null>(null)
let confirming = $state(false)
let downloading = $state(false)
let actionError = $state<string | null>(null)
let downloadError = $state<string | null>(null)
const initialDocument = $derived(artifact.type === 'broker_document' ? artifact.data : null)
const documentQuery = createQuery(() =>
	brokerQueries.document(initialDocument?.id ?? null, initialDocument ?? undefined)
)
// A failed authorization refresh must not leave a cached private document visible.
const savedDocument = $derived(documentQuery.isError ? null : documentQuery.data)
const action = $derived(artifact.type === 'broker_action' ? (confirmation ?? artifact.data) : null)

async function confirmAction() {
	if (!action || action.status !== 'proposal' || confirming) return
	confirming = true
	actionError = null
	try {
		const result = await broker.confirmAction(action.proposal.proposal_id)
		if (result.status !== 'completed') throw new Error('The action has not been confirmed.')
		confirmation = result
		await getQueryClient().invalidateQueries({ queryKey: inboundKeys.all })
	} catch (error) {
		actionError = error instanceof Error ? error.message : 'Could not confirm the action.'
	} finally {
		confirming = false
	}
}

async function download() {
	if (!savedDocument || savedDocument.status !== 'completed' || downloading) return
	downloading = true
	downloadError = null
	try {
		// Only the authenticated ID route is trusted, never a URL from artifact content.
		const blob = await broker.downloadDocument(savedDocument.id)
		const url = URL.createObjectURL(blob)
		try {
			const link = document.createElement('a')
			link.href = url
			link.download = `${savedDocument.document.reference.replace(/[^a-zA-Z0-9_-]/g, '_')}-v${savedDocument.version}.pdf`
			link.click()
		} finally {
			URL.revokeObjectURL(url)
		}
	} catch (error) {
		downloadError = error instanceof Error ? error.message : 'Could not download this document.'
	} finally {
		downloading = false
	}
}
</script>

<section class="overflow-hidden rounded-lg border border-border bg-white shadow-sm" aria-label={artifact.title}>
	<header class="border-b border-border bg-panel px-4 py-3">
		<h3 class="text-sm font-semibold text-fg-1">{artifact.title}</h3>
		<p class="mt-1 text-xs text-fg-4">{artifact.type === 'broker_document' ? 'Saved broker document' : 'Broker action'}</p>
	</header>
	<div class="space-y-4 p-4 text-sm text-fg-2">
		{#if artifact.status === 'error'}
			<p role="alert" class="text-error">{artifact.error ?? 'This result could not be prepared.'}</p>
		{:else if artifact.type === 'broker_action'}
			{#if action}
				<p class="font-medium">{action.proposal.action === 'note' ? 'Add note' : 'Schedule follow-up'} · Enquiry {action.proposal.enquiry_id}</p>
				{#if action.proposal.body}<p class="whitespace-pre-wrap">{action.proposal.body}</p>{/if}
				{#if action.proposal.due_date}<p>Due date: {action.proposal.due_date}</p>{/if}
				{#if action.status === 'completed'}
					<p role="status" class="text-success">{action.proposal.action === 'note' ? 'Note saved.' : 'Follow-up scheduled.'}</p>
				{:else}
					<p class="text-xs text-fg-4">Review this proposal before confirming. The server checks whether it has already been applied.</p>
					<button type="button" class="ui-button ui-button-primary" disabled={confirming} onclick={confirmAction}>
						{#if confirming}<Loader2 size={14} class="animate-spin" />{/if}
						{confirming ? 'Confirming…' : 'Confirm action'}
					</button>
				{/if}
				{#if actionError}<p role="alert" class="text-error">{actionError}</p>{/if}
			{:else}<p role="status">The proposal is not available.</p>{/if}
		{:else if documentQuery.isError}
			<p role="alert" class="text-error">Could not load this document. Access may have changed.</p>
		{:else if !savedDocument || savedDocument.status === 'queued' || savedDocument.status === 'running'}
			<p role="status" class="flex items-center gap-2"><Loader2 size={16} class="animate-spin" />{savedDocument?.status === 'queued' ? 'Document queued.' : 'Preparing document…'}</p>
		{:else if savedDocument.status === 'failed'}
			<p role="alert" class="text-error">{savedDocument.error ?? 'Document generation failed.'}</p>
		{:else}
			{@const data = savedDocument.document}
			<div>
				<p class="text-xs font-semibold uppercase tracking-wide text-fg-4">{data.brand}</p>
				<h4 class="mt-1 text-base font-semibold text-fg-1">{data.title}</h4>
				<p class="mt-1 text-xs text-fg-4">{data.reference} · Version {data.version} · Prepared {data.prepared_at}</p>
				{#if data.valid_until}<p class="mt-1 text-xs text-fg-4">Valid until {data.valid_until}</p>{/if}
			</div>
			{#each data.properties as property}
				<article class="space-y-2 rounded-md border border-border p-3">
					<h5 class="font-semibold">{property.title}</h5>
					<p class="text-xs text-fg-4">{property.reference} · Evidence date: {property.evidence_date}</p>
					<p>Asking price: {property.asking_price === null ? 'Not available' : `${property.currency} ${property.asking_price} ${property.price_unit}`}</p>
					<dl class="grid gap-1">{#each property.facts as fact}<div class="flex flex-wrap justify-between gap-2"><dt class="text-fg-4">{fact.label}</dt><dd>{fact.value}</dd></div>{/each}</dl>
					{#each [{ title: 'Selling points', values: property.selling_points }, { title: 'Trade-offs', values: property.trade_offs }, { title: 'Missing information', values: property.missing_information }] as group}
						{#if group.values.length}<div><p class="text-xs font-semibold">{group.title}</p><ul class="ml-4 list-disc text-xs leading-5">{#each group.values as value}<li>{value}</li>{/each}</ul></div>{/if}
					{/each}
				</article>
			{/each}
			{#each data.sections ?? [] as section}
				<section class="space-y-2"><h5 class="font-semibold">{section.title}</h5><dl class="grid gap-1">{#each section.rows as row}<div class="flex flex-wrap justify-between gap-2"><dt class="text-fg-4">{row.label}</dt><dd class="whitespace-pre-wrap">{row.value}</dd></div>{/each}</dl></section>
			{/each}
			{#if data.quotation}
				{@const quote = data.quotation}
				<section class="space-y-2" aria-label="Quotation">
					<h5 class="font-semibold">Quotation · {quote.currency}</h5>
					{#each quote.lines as line}
						<div class="rounded border border-border p-2"><p class="flex justify-between gap-2"><span>{line.label} ({line.status})</span><span>{line.amount === null ? 'Not available' : `${quote.currency} ${line.amount}`}</span></p><p class="mt-1 text-xs text-fg-4">{line.basis}</p></div>
					{/each}
					<dl class="space-y-1"><div class="flex justify-between gap-2"><dt>Known charges</dt><dd>{quote.currency} {quote.known_total}</dd></div><div class="flex justify-between gap-2"><dt>Estimated charges</dt><dd>{quote.currency} {quote.estimated_total}</dd></div><div class="flex justify-between gap-2 font-semibold"><dt>Total</dt><dd>{quote.total === null ? 'Not available — charges are missing' : `${quote.currency} ${quote.total}`}</dd></div></dl>
					{#if quote.missing_charges.length}<p class="text-xs text-fg-4">Missing charges: {quote.missing_charges.join(', ')}</p>{/if}
				</section>
			{/if}
			{#if data.limitations.length}<section><h5 class="text-xs font-semibold">Limitations</h5><ul class="ml-4 list-disc text-xs leading-5 text-fg-4">{#each data.limitations as limitation}<li>{limitation}</li>{/each}</ul></section>{/if}
			{#if savedDocument.download_url}
				<button type="button" class="ui-button ui-button-primary" disabled={downloading} onclick={download}><Download size={14} />{downloading ? 'Downloading…' : `Download PDF · Version ${savedDocument.version}`}</button>
			{/if}
			{#if downloadError}<p role="alert" class="text-error">{downloadError}</p>{/if}
		{/if}
	</div>
</section>
