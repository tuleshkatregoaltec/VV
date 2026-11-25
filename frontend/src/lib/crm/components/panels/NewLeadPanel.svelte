<script lang="ts">
import { untrack } from 'svelte'
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type { LeadFieldKey, LeadFields, LeadType } from '../../api/types'
import { fieldShown, LEAD_TYPE_ORDER, LEAD_TYPES, SOURCE_OPTIONS } from '../../config'
import { phoneProblem } from '../../format'
import { clearLeadFilters, ui } from '../../stores/ui.svelte'
import { write } from '../../write'
import MoneyInput from '../ui/MoneyInput.svelte'
import Panel from '../ui/Panel.svelte'
import Seg from '../ui/Seg.svelte'

/**
 * Type switch first; name, phone, source and area survive a type switch.
 * With `qualify`, the same form qualifies an Inbox contact in place: its name, phone and source
 * are already on the enquiry, so only the lead type and its brief are asked for.
 */
let {
	leadType,
	qualify
}: {
	leadType?: LeadType
	qualify?: { id: number; name: string; prefill?: { area: string; fields: LeadFields } }
} = $props()

let type = $state<LeadType>(untrack(() => leadType ?? 'buyer'))
let name = $state('')
let phone = $state('')
let sourceLabel = $state(SOURCE_OPTIONS[0].label)
let area = $state(untrack(() => qualify?.prefill?.area ?? ''))
let draft = $state<Record<string, string>>(
	untrack(() =>
		Object.fromEntries(
			Object.entries(qualify?.prefill?.fields ?? {}).filter(([, value]) => typeof value === 'string')
		)
	)
)
let money = $state<Record<string, number | null>>(
	untrack(() =>
		Object.fromEntries(
			Object.entries(qualify?.prefill?.fields ?? {}).filter(([, value]) => typeof value === 'number')
		)
	)
)
let saving = $state(false)

const fields = $derived(LEAD_TYPES[type].fields)
const areaRequired = $derived(LEAD_TYPES[type].areaRequired ?? false)

/**
 * `required` only checks that a box is not empty: a name of spaces, a budget typed as letters or
 * an unusable phone would get through, and the backend would reject or quietly drop them.
 */
function problems(): [string, string][] {
	const list: [string, string][] = [
		['nl-area', areaRequired && !area.trim() ? 'Enter an area.' : '']
	]
	if (!qualify)
		list.push(['nl-name', name.trim() ? '' : 'Enter a name.'], ['nl-phone', phoneProblem(phone)])
	for (const f of fields.filter((x) => x.required)) {
		const filled = f.money ? Boolean(money[f.key]) : Boolean(String(draft[f.key] ?? '').trim())
		list.push([`nl-${f.key}`, filled ? '' : `Enter the ${f.label.toLowerCase()}.`])
	}
	return list
}

async function submit(e: SubmitEvent) {
	e.preventDefault()
	const form = e.currentTarget as HTMLFormElement
	for (const [id, problem] of problems())
		form.querySelector<HTMLInputElement>(`#${id}`)?.setCustomValidity(problem)
	if (!form.reportValidity()) return
	const option = SOURCE_OPTIONS.find((s) => s.label === sourceLabel) ?? SOURCE_OPTIONS[0]
	const out: LeadFields = {}
	for (const f of fields) {
		const k = f.key as LeadFieldKey
		if (!fieldShown(f, draft)) continue
		if (f.money) {
			if (money[k]) out[k] = money[k]
		} else {
			const raw = String(draft[k] ?? '').trim()
			if (raw) out[k] = raw
		}
	}
	saving = true
	const r = qualify
		? await write({
				domain: 'leads',
				call: () =>
					crm.inbox.qualify(qualify.id, { lead_type: type, area: area.trim(), fields: out }),
				success: (res) => `${res.data.name} is now a ${LEAD_TYPES[type].label.toLowerCase()} lead`
			})
		: await write({
				domain: 'leads',
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

<Panel kicker={qualify ? 'Inbox' : 'New'} title={qualify ? `Qualify ${qualify.name}` : 'Lead'}>
	<form
		class="form"
		onsubmit={submit}
		oninput={(e) => (e.target as HTMLInputElement).setCustomValidity?.('')}
	>
		<div class="fld">
			<span class="fl" id="new-lead-type">Lead type</span>
			<Seg
				label="Lead type"
				items={LEAD_TYPE_ORDER.map((t) => ({ id: t, label: LEAD_TYPES[t].label }))}
				value={type}
				onselect={(t) => (type = t)}
			/>
		</div>
		{#if !qualify}
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
		{/if}
		{#each fields.filter((x) => fieldShown(x, draft)) as f (f.key)}
			<div class="fld">
				<label for="nl-{f.key}">{f.label}{f.money ? ' (AED)' : ''}</label>
				{#if f.money}
					<MoneyInput id="nl-{f.key}" required={f.required} bind:value={money[f.key]} />
				{:else if f.options}
					<select id="nl-{f.key}" bind:value={draft[f.key]}>
						<option value="">Not stated</option>
						{#each f.options as o (o)}<option value={o}>{o}</option>{/each}
					</select>
				{:else}
					<input id="nl-{f.key}" type={f.date ? 'date' : 'text'} required={f.required} bind:value={draft[f.key]} />
				{/if}
			</div>
		{/each}
		<div class="fld">
			<label for="nl-area">Area</label>
			<input id="nl-area" placeholder="JVC" required={areaRequired} bind:value={area} />
		</div>
		<div><button type="submit" class="btn" disabled={saving}>{qualify ? 'Qualify lead' : 'Create lead'}</button></div>
	</form>
</Panel>
