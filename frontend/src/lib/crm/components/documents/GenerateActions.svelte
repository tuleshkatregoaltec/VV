<script lang="ts">
/** Generate buttons for one managed listing; each click asks for exactly one PDF. */
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import type { DocType } from '../../api/types'
import { crmKeys, crmQueries } from '../../queries'
import { toast } from '../../stores/toast.svelte'
import { errorText } from '../../write'
import { DOC_TYPES, docLabel, type GenerateOutcome, generate } from './documentRules'

let { listingKey }: { listingKey: string } = $props()

const qc = useQueryClient()
const info = createQuery(() => crmQueries.documentInfo(listingKey))

let pending = $state<DocType | null>(null)
let problem = $state<{ type: DocType; outcome: Exclude<GenerateOutcome, { ok: true }> } | null>(
	null
)

async function run(type: DocType) {
	const revision = info.data?.revision ?? 0
	if (pending || revision < 1) return
	pending = type
	problem = null
	const outcome = await generate(listingKey, type, revision)
	pending = null
	await qc.invalidateQueries({ queryKey: crmKeys.documentsAll() })
	if (outcome.ok) toast.show(`${docLabel(type)} PDF ready to download`)
	else problem = { type, outcome }
}
</script>

<section class="sec" aria-labelledby="gen-{listingKey}">
	<h3 id="gen-{listingKey}">Generate PDF</h3>
	{#if (info.data?.revision ?? 0) < 1}
		<div class="small muted">Save the document information first; PDFs use the saved details.</div>
	{/if}
	<div class="gen">
		{#each DOC_TYPES as d (d.type)}
			<button
				type="button"
				class="btn ghost sm"
				disabled={pending !== null || (info.data?.revision ?? 0) < 1}
				aria-busy={pending === d.type}
				onclick={() => run(d.type)}
			>
				{pending === d.type ? `Making ${d.label}…` : d.label}
			</button>
		{/each}
	</div>
	{#if problem}
		{@const label = docLabel(problem.type)}
		<div class="errline" role="alert">
			{#if problem.outcome.kind === 'missing'}
				<span>{label} needs: {problem.outcome.fields.join(', ')}.</span>
			{:else if problem.outcome.kind === 'stale'}
				<span>The information changed since it loaded. Reload it, check it, then generate again.</span>
			{:else if problem.outcome.kind === 'failed'}
				<span>The {label} PDF could not be made. Nothing was saved to download.</span>
				<button type="button" class="btn ghost sm" onclick={() => problem && run(problem.type)}>Try again</button>
			{:else}
				<span>{errorText(problem.outcome.error)}</span>
			{/if}
		</div>
	{/if}
</section>

<style>
	.gen {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
</style>
