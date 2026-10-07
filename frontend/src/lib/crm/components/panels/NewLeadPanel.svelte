<script lang="ts">
import { untrack } from 'svelte'
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type { LeadFieldKey, LeadFields, LeadType } from '../../api/types'
import { LEAD_TYPE_ORDER, LEAD_TYPES, SOURCE_OPTIONS } from '../../config'
import { clearLeadFilters, ui } from '../../stores/ui.svelte'
import { write } from '../../write'
import MoneyInput from '../ui/MoneyInput.svelte'
import Panel from '../ui/Panel.svelte'
import Seg from '../ui/Seg.svelte'

/** Type switch first; name, phone, source and area survive a type switch. */
let { leadType }: { leadType?: LeadType } = $props()

let type = $state<LeadType>(untrack(() => leadType ?? 'buyer'))
let name = $state('')
let phone = $state('')
let sourceLabel = $state(SOURCE_OPTIONS[0].label)
let area = $state('')
let draft = $state<Record<string, string>>({})
let money = $state<Record<string, number | null>>({})
let saving = $state(false)

const fields = $derived(LEAD_TYPES[type].fields)

async function submit(e: SubmitEvent) {
	e.preventDefault()
	const option = SOURCE_OPTIONS.find((s) => s.label === sourceLabel) ?? SOURCE_OPTIONS[0]
	const out: LeadFields = {}
	for (const f of fields) {
		const k = f.key as LeadFieldKey
		if (f.money) {
			if (money[k]) out[k] = money[k]
		} else {
			const raw = String(draft[k] ?? '').trim()
			if (raw) out[k] = raw
		}
	}
	saving = true
	const r = await write({
		call: () =>
			crm.leads.create({
				name: name.trim(),
				phone,
				source: option.source,
				source_detail: option.label,
				lead_type: type,
				area: area.trim(),
				fields: out
			}),
		success: (res) => `${res.data.name} created`,
		created: (res) => ({ kind: 'lead', id: res.data.id }),
		event: 'lead_created'
	})
	saving = false
	if (r) {
		ui.leadTab = 'all'
		clearLeadFilters()
		await goto(`/crm/leads?lead=${r.data.id}`)
	}
}
</script>

<Panel kicker="New" title="Lead">
	<form class="form" onsubmit={submit}>
		<div class="fld">
			<span class="fl" id="new-lead-type">Lead type</span>
			<Seg
				label="Lead type"
				items={LEAD_TYPE_ORDER.map((t) => ({ id: t, label: LEAD_TYPES[t].label }))}
				value={type}
				onselect={(t) => (type = t)}
			/>
		</div>
		<div class="fld">
			<label for="nl-name">Name</label>
			<input id="nl-name" required autocomplete="off" bind:value={name} />
		</div>
		<div class="frow">
			<div class="fld">
				<label for="nl-phone">Phone</label>
				<input
					id="nl-phone"
					inputmode="tel"
					autocomplete="off"
					placeholder="050 123 4567"
					required
					bind:value={phone}
				/>
			</div>
			<div class="fld">
				<label for="nl-source">Source</label>
				<select id="nl-source" bind:value={sourceLabel}>
					{#each SOURCE_OPTIONS as s (s.label)}<option value={s.label}>{s.label}</option>{/each}
				</select>
			</div>
		</div>
		{#each fields as f (f.key)}
			<div class="fld">
				<label for="nl-{f.key}">{f.label}{f.money ? ' (AED)' : ''}</label>
				{#if f.money}
					<MoneyInput id="nl-{f.key}" bind:value={money[f.key]} />
				{:else if f.options}
					<select id="nl-{f.key}" bind:value={draft[f.key]}>
						<option value="">Not stated</option>
						{#each f.options as o (o)}<option value={o}>{o}</option>{/each}
					</select>
				{:else}
					<input id="nl-{f.key}" type="text" bind:value={draft[f.key]} />
				{/if}
			</div>
		{/each}
		<div class="fld">
			<label for="nl-area">Area</label>
			<input id="nl-area" placeholder="JVC" bind:value={area} />
		</div>
		<div><button type="submit" class="btn" disabled={saving}>Create lead</button></div>
	</form>
</Panel>
