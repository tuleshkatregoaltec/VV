<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { goto } from '$app/navigation'
import type { LeadDetail } from '../../../api/types'
import { crmQueries } from '../../../queries'
import { panel } from '../../../stores/panel.svelte'
import { type MatchTabId, ui } from '../../../stores/ui.svelte'
import { errorText } from '../../../write'
import BudgetRange from '../../ui/BudgetRange.svelte'
import ErrorLine from '../../ui/ErrorLine.svelte'
import MatchTiers from '../../ui/MatchTiers.svelte'
import Skeleton from '../../ui/Skeleton.svelte'

/** The lead's Matches tab: the same tiers as the Matches section, for this lead. */
let { lead }: { lead: LeadDetail } = $props()

let after = $state(false)
const matches = createQuery(() => crmQueries.leadMatches(lead.id, { over: ui.matchOver, after }))
/** Keep showing the previous tiers only while the same lead reloads, never another lead's. */
const m = $derived(matches.data && matches.data.lead.id === lead.id ? matches.data : null)

const tab = $derived<MatchTabId>(
	lead.lead_type === 'seller' || lead.lead_type === 'landlord'
		? 'sell'
		: lead.off_plan
			? 'offplan'
			: 'ready'
)

function openInMatches() {
	ui.matchTab = tab
	ui.matchSel[tab] = lead.id
	panel.closeAll()
	void goto('/crm/matches')
}
</script>

<div class="filters">
	{#if tab !== 'sell' && Number(lead.fields.budget_aed)}
		<BudgetRange budget={Number(lead.fields.budget_aed)} rent={lead.lead_type === 'tenant'} />
	{/if}
	<span class="count">
		<button type="button" class="btn ghost sm" onclick={openInMatches}>Open in Matches</button>
	</span>
</div>

<!-- A thin bar while matches load: first load, a refresh, or the after-move toggle. -->
<div class="loadtrack" aria-hidden="true">
	{#if matches.isFetching}<span></span>{/if}
</div>

{#if m}
	{#if matches.isError}
		<ErrorLine bar message={errorText(matches.error)} onretry={() => matches.refetch()} />
	{/if}
	<div class="panel-tiers" class:dim={matches.isFetching}>
		<MatchTiers data={m} bind:after />
	</div>
{:else if matches.isError}
	<ErrorLine message={errorText(matches.error)} onretry={() => matches.refetch()} />
{:else}
	<div class="panel-tiers">
		<div class="card"><Skeleton rows={2} /></div>
		<div class="card"><Skeleton rows={2} /></div>
		<div class="card"><Skeleton rows={4} /></div>
	</div>
{/if}

<style>
	/* Same indeterminate bar as Company listings */
	.loadtrack {
		position: relative;
		height: 2px;
		margin: 0 0 8px;
		overflow: hidden;
	}
	.loadtrack span {
		position: absolute;
		inset: 0 auto 0 0;
		width: 35%;
		background: var(--accent);
		border-radius: 2px;
		animation: loadbar 1.1s ease-in-out infinite;
	}
	@keyframes loadbar {
		0% {
			transform: translateX(-100%);
		}
		100% {
			transform: translateX(300%);
		}
	}
	.dim {
		opacity: 0.5;
		transition: opacity 0.15s;
	}
</style>
