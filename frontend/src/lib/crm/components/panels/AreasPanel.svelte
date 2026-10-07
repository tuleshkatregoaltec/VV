<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../api'
import { fmt } from '../../format'
import { crmQueries } from '../../queries'
import { panel } from '../../stores/panel.svelte'
import { toast } from '../../stores/toast.svelte'
import { write } from '../../write'
import Panel from '../ui/Panel.svelte'
import QueryView from '../ui/QueryView.svelte'

/** My areas: the Leads feed strip counts lease ends in these; owner-file leads come from them. */
const areas = createQuery(() => crmQueries.feedAreas())
const summary = createQuery(() => crmQueries.feedSummary())

let picked = $state<Set<string> | null>(null)
const selected = $derived(picked ?? new Set(summary.data?.areas ?? []))

function toggle(area: string, on: boolean) {
	const next = new Set(selected)
	if (on) next.add(area)
	else next.delete(area)
	picked = next
}

async function save() {
	const list = [...selected]
	if (!list.length) {
		toast.show('Pick at least one area', { tone: 'error' })
		return
	}
	const r = await write({
		call: () => crm.feed.setAreas(list),
		success: `Areas saved · ${list.length}`
	})
	if (r) panel.close()
}
</script>

<Panel kicker="Lease ends in 90 days" title="My areas" sub="{selected.size} chosen">
	<QueryView query={areas} rows={6}>
		{#snippet children(list)}
			<fieldset class="docs">
				<legend class="sr-only">Areas</legend>
				{#each list as a (a.area)}
					<label class="doc" style="grid-template-columns:auto minmax(0,1fr) auto;cursor:pointer">
						<input
							type="checkbox"
							checked={selected.has(a.area)}
							onchange={(e) => toggle(a.area, e.currentTarget.checked)}
						/>
						<span>{a.area}</span>
						<span class="small muted num" title="Units with a lease ending in the next 90 days">
							{fmt(a.owners_in_90_day_window)}
						</span>
					</label>
				{/each}
			</fieldset>
		{/snippet}
	</QueryView>
	{#snippet footer()}
		<button type="button" class="btn" onclick={save}>Save</button>
	{/snippet}
</Panel>
