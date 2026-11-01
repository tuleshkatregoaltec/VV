<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { goto } from '$app/navigation'
import { aed, fmt, fullDate } from '../../format'
import { clampOffset, STATUS_INFO } from '../../ownerImportReport'
import { crmQueries } from '../../queries'
import { panel } from '../../stores/panel.svelte'
import Chip from '../ui/Chip.svelte'
import Empty from '../ui/Empty.svelte'
import QueryView from '../ui/QueryView.svelte'
import OwnerHistorySummary from './OwnerHistorySummary.svelte'

let { id }: { id: string } = $props()
let offset = $state(0)
const limit = 25
$effect.pre(() => {
	void id
	offset = 0
})
const history = createQuery(() => crmQueries.ownerHistory(id, { limit, offset }))
$effect(() => {
	const data = history.data
	if (!data) return
	const next = clampOffset(data.offset, data.total, data.limit)
	if (next !== offset) offset = next
})

async function openSource(importId: number) {
	panel.closeAll()
	await goto(`/crm/owners/imports/${importId}`)
}
const statusInfo = (status: string) => STATUS_INFO[status as keyof typeof STATUS_INFO]
</script>

<QueryView query={history} rows={3}>
	{#snippet children(data)}
		<OwnerHistorySummary summary={data.summary} />
		<section class="sec" aria-label="Ownership history">
			<h3>Ownership history</h3>
			{#if data.events.length}
				<ol class="events">
					{#each data.events as event (event.id)}
						<li class="event">
							<div class="title">
								<strong>{event.transaction_date ? fullDate(event.transaction_date) : 'Date unknown'}</strong>
								<Chip tone={statusInfo(event.current_ownership_status)?.tone ?? 'neutral'}>{statusInfo(event.current_ownership_status)?.label ?? event.current_ownership_status}</Chip>
							</div>
							<div>{[event.building_name || event.project_name, event.unit_number && `Unit ${event.unit_number}`, event.area_name].filter(Boolean).join(' · ') || 'Property not identified'}</div>
							{#if !event.property_key}<div class="small muted">Property not resolved</div>{/if}
							<div class="small">Role: {event.party_role || 'Not supplied'} · Procedure: {event.procedure_type || 'Not supplied'}</div>
							{#if event.transaction_price_aed != null}<div class="small">Recorded amount: {aed(event.transaction_price_aed)}</div>{/if}
							{#if event.current_evidence_reason || event.evidence_reason}<div class="small">{event.current_evidence_reason || event.evidence_reason}</div>{/if}
							<button type="button" class="source" onclick={() => openSource(event.import_id)}>{event.source_filename || `Import #${event.import_id}`}</button>
							<div class="small muted">{event.source_sheet || 'Sheet unknown'} · {event.source_row_number === null ? 'Row unknown' : `Row ${event.source_row_number}`}</div>
						</li>
					{/each}
				</ol>
			{:else}
				<Empty text="No ownership history." />
			{/if}
			<div class="paging">
				<span class="small muted" aria-live="polite">{data.total ? `${fmt(data.offset + 1)}–${fmt(data.offset + data.events.length)} of ${fmt(data.total)} events` : '0 events'}</span>
				<button type="button" class="btn ghost sm" disabled={data.offset === 0 || history.isFetching} onclick={() => (offset = Math.max(0, data.offset - limit))}>Previous events</button>
				<button type="button" class="btn ghost sm" disabled={data.offset + data.events.length >= data.total || history.isFetching} onclick={() => (offset = data.offset + limit)}>Next events</button>
			</div>
		</section>
	{/snippet}
</QueryView>

<style>
	.events {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.65rem;
	}
	.event {
		border: 1px solid var(--line);
		border-radius: 8px;
		padding: 0.75rem;
		display: grid;
		gap: 0.3rem;
	}
	.title, .paging {
		display: flex;
		align-items: center;
		flex-wrap: wrap;
		gap: 0.5rem;
	}
	.paging {
		margin-top: 0.75rem;
	}
	.source {
		justify-self: start;
		padding: 0;
		border: 0;
		background: none;
		color: var(--accent);
		font: inherit;
		text-align: left;
		cursor: pointer;
	}
</style>
