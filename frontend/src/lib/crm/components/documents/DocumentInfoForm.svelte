<script lang="ts">
/** Owner, agreement and A2A details saved for one managed listing (one revision at a time). */
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import { ApiError } from '$lib/api/client'
import type { ListingDocumentInfoResponse } from '$lib/api/generated/hey-api/types.gen'
import { crm } from '../../api'
import { crmKeys, crmQueries } from '../../queries'
import { toast } from '../../stores/toast.svelte'
import { errorText } from '../../write'
import ErrorLine from '../ui/ErrorLine.svelte'
import { fieldLabel } from './documentRules'

let { listingKey }: { listingKey: string } = $props()

type Group = 'owner' | 'lease' | 'a2a'
type Field = {
	key: string
	type: 'text' | 'tel' | 'email' | 'date' | 'number'
	min?: number
	max?: number
}

const SECTIONS: { group: Group; title: string; fields: Field[] }[] = [
	{
		group: 'owner',
		title: 'Owner information',
		fields: [
			{ key: 'full_name', type: 'text' },
			{ key: 'phone', type: 'tel' },
			{ key: 'email', type: 'email' },
			{ key: 'title_deed_number', type: 'text' },
			{ key: 'id_number', type: 'text' }
		]
	},
	{
		group: 'lease',
		title: 'Agreement information',
		fields: [
			{ key: 'tenant_name', type: 'text' },
			{ key: 'tenant_phone', type: 'tel' },
			{ key: 'tenant_email', type: 'email' },
			{ key: 'start_date', type: 'date' },
			{ key: 'end_date', type: 'date' },
			{ key: 'annual_rent_aed', type: 'number', min: 0 },
			{ key: 'cheques', type: 'number', min: 1, max: 12 },
			{ key: 'security_deposit_aed', type: 'number', min: 0 }
		]
	},
	{
		group: 'a2a',
		title: 'A2A agreement info',
		fields: [
			{ key: 'other_brokerage', type: 'text' },
			{ key: 'other_broker_name', type: 'text' },
			{ key: 'other_broker_brn', type: 'text' },
			{ key: 'commission_split_pct', type: 'number', min: 0, max: 100 },
			{ key: 'valid_until', type: 'date' }
		]
	}
]

type Draft = Record<Group, Record<string, string | number | null>>

const qc = useQueryClient()
const info = createQuery(() => crmQueries.documentInfo(listingKey))

let draft = $state<Draft | null>(null)
let loadedRevision = $state(-1)
let saving = $state(false)
let conflict = $state(false)

function toDraft(r: ListingDocumentInfoResponse): Draft {
	const f = r.fields as unknown as Draft
	return {
		owner: { ...f.owner },
		lease: { ...f.lease },
		a2a: { ...f.a2a }
	}
}

// Take the saved values when they load, and again after a save or reload brings a new revision.
$effect(() => {
	const data = info.data
	if (data && data.revision !== loadedRevision) {
		draft = toDraft(data)
		loadedRevision = data.revision
	}
})

/** Blank inputs are "not given" (null), never an empty value printed into a document. */
function clean(d: Draft) {
	const out: Record<string, Record<string, string | number | null>> = {}
	for (const [group, values] of Object.entries(d)) {
		out[group] = {}
		for (const [k, v] of Object.entries(values)) {
			out[group][k] =
				v === '' || v === undefined || (typeof v === 'number' && Number.isNaN(v)) ? null : v
		}
	}
	return out
}

async function save(e: SubmitEvent) {
	e.preventDefault()
	if (!draft || !info.data || saving) return
	saving = true
	conflict = false
	try {
		const saved = await crm.documents.saveInfo({
			source: 'property_finder',
			listing_key: listingKey,
			fields: clean(draft) as never,
			expected_revision: info.data.revision
		})
		qc.setQueryData(crmKeys.documentInfo(listingKey), saved)
		toast.show('Document information saved')
	} catch (err) {
		if (err instanceof ApiError && err.status === 409) conflict = true
		else toast.show(errorText(err), { tone: 'error' })
	} finally {
		saving = false
	}
}

async function reload() {
	conflict = false
	loadedRevision = -1
	await info.refetch()
}
</script>

{#if info.isError}
	<ErrorLine message={errorText(info.error)} onretry={() => info.refetch()} />
{:else if draft}
	{@const d = draft}
	<form class="form" onsubmit={save} aria-label="Document information">
		{#each SECTIONS as s (s.group)}
			<section class="sec">
				<h3>{s.title}</h3>
				<div class="frow wrap">
					{#each s.fields as f (f.key)}
						{@const id = `doc-${s.group}-${f.key}`}
						<div class="fld">
							<label for={id}>{fieldLabel(`${s.group}.${f.key}`)}</label>
							{#if f.type === 'number'}
								<input {id} type="number" min={f.min} max={f.max} bind:value={d[s.group][f.key]} />
							{:else}
								<input {id} type={f.type} maxlength="200" bind:value={d[s.group][f.key]} />
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/each}
		{#if conflict}
			<div class="errline" role="alert">
				<span>Someone else changed this information. Reload to see their version.</span>
				<button type="button" class="btn ghost sm" onclick={reload}>Reload</button>
			</div>
		{/if}
		<div class="form-actions">
			<button type="submit" class="btn" disabled={saving}>{saving ? 'Saving…' : 'Save information'}</button>
			<span class="small muted">Only your agency sees these details.</span>
		</div>
	</form>
{:else}
	<div class="small muted">Loading document information…</div>
{/if}

<style>
	.wrap {
		flex-wrap: wrap;
	}
	.wrap .fld {
		flex: 1 1 14rem;
	}
</style>
