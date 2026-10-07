<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { untrack } from 'svelte'
import { crm } from '../../api'
import type { Renewal } from '../../api/types'
import { aed, dayLabel } from '../../format'
import { crmQueries } from '../../queries'
import { openDeal } from '../../stores/panel.svelte'
import { toast } from '../../stores/toast.svelte'
import { errorText, write } from '../../write'
import Chip from '../ui/Chip.svelte'
import Kv from '../ui/Kv.svelte'
import Panel from '../ui/Panel.svelte'
import PanelLoading from '../ui/PanelLoading.svelte'

/** Rent now vs building median, days to lease end, a draft message, Start renewal. */
let { id }: { id: number } = $props()
const renewals = createQuery(() => crmQueries.renewals())
const r = $derived(renewals.data?.find((x) => x.id === id))

let draft = $state(untrack(() => r?.draft ?? ''))
$effect(() => {
	if (!draft && r) draft = r.draft
})

function start(x: Renewal) {
	write({ call: () => crm.renewals.start(x.id), success: `Renewal started — ${x.unit}` })
}

async function send() {
	try {
		await crm.renewals.send(id)
		toast.show('Draft sent')
	} catch (e) {
		toast.show(errorText(e), { tone: 'error' })
	}
}
</script>

{#if r}
	<Panel kicker="Renewal" title={r.unit} sub={r.party}>
		{#snippet tags()}<Chip chip={r.end_chip} />{/snippet}
		<div class="kv">
			<Kv k="Rent now" v={aed(r.rent_aed)} />
			<Kv k="Building median" v={aed(r.building_median_aed)} o={r.gap_chip.label} />
			<Kv k="Lease ends" v={dayLabel(r.lease_end)} o="{r.days_left} days" />
			<Kv k="Status">
				{#if r.started && r.deal_id}
					<button type="button" class="btn ghost sm" onclick={() => r.deal_id && openDeal(r.deal_id)}>
						Started · {r.deal_id}
					</button>
				{:else}
					Not started
				{/if}
			</Kv>
		</div>
		<div class="fld">
			<label for="renewal-draft">Message draft</label>
			<textarea id="renewal-draft" rows="5" bind:value={draft}></textarea>
		</div>
		{#snippet footer()}
			{#if !r.started}<button type="button" class="btn" onclick={() => start(r)}>Start renewal</button>{/if}
			<button type="button" class={['btn', !r.started && 'ghost']} onclick={send}>Send draft</button>
		{/snippet}
	</Panel>
{:else}
	<PanelLoading query={renewals} kicker="Renewal" />
{/if}
