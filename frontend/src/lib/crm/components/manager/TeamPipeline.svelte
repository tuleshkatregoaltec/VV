<script lang="ts">
import type { Tone } from '$lib/crm/api/types'
import FilterMenu from '$lib/crm/components/ui/FilterMenu.svelte'
import StageChip from '$lib/crm/components/ui/StageChip.svelte'
import { stageOf } from '$lib/crm/config'
import { type MgrData, stageCounts, type ViewAs } from '$lib/crm/mock/manager'
import PrivacyTag from './PrivacyTag.svelte'

/** Leads by stage as bars. Manager can narrow to one agent; Agent view is already their own leads. */
let { data, view }: { data: MgrData; view: ViewAs } = $props()

let agentId = $state('')
// An agent picked in Manager view means nothing in Agent view.
$effect(() => {
	if (view === 'agent') agentId = ''
})

const counts = $derived(stageCounts(data.leads, agentId ? Number(agentId) : null))
const max = $derived(Math.max(1, ...counts.map((c) => c.count)))
const total = $derived(counts.reduce((n, c) => n + c.count, 0))

/**
 * The card often sits low on the screen. Before the menu opens (capture runs before the button's
 * own click/keydown), open it upwards when there is more room above, and cap its height to the
 * room it has, so the whole list shows without scrolling the page.
 */
let menuUp = $state(false)
let menuMax = $state(400)
function placeMenu(e: Event) {
	const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
	const below = window.innerHeight - r.bottom - 12
	const above = r.top - 12
	menuUp = below < 460 && above > below
	menuMax = Math.max(160, Math.floor(menuUp ? above : below))
}

/** Bar colour follows the stage chip's tone. */
const FILL: Partial<Record<Tone, string>> = {
	blue: 'var(--blue)',
	green: 'var(--green)',
	amber: 'var(--amber)',
	red: 'var(--red)'
}
</script>

<section class="card pl" aria-labelledby="pl-h">
	<div class="ch">
		<h2 id="pl-h">
			{view === 'manager' ? 'Team pipeline' : 'Your pipeline'} <span class="ct">· {total} leads</span>
		</h2>
		{#if view === 'manager'}
			<div
				class={['tools', menuUp && 'up']}
				style:--menu-max="{menuMax}px"
				role="none"
				onclickcapture={placeMenu}
				onkeydowncapture={placeMenu}
			>
				<PrivacyTag k="otherLeads" {view} />
				<FilterMenu
					label="Agent"
					allLabel="All agents"
					value={agentId}
					options={data.agents.map((a) => ({ id: String(a.id), label: a.name }))}
					onselect={(v) => (agentId = v)}
				/>
			</div>
		{/if}
	</div>
	<ul class="bars">
		{#each counts as c (c.stage)}
			<li>
				<span class="lbl"><StageChip stage={c.stage} /></span>
				<span class="track" aria-hidden="true">
					<span
						class="fill"
						style:width="{(c.count / max) * 100}%"
						style:background={FILL[stageOf(c.stage).tone] ?? 'var(--text2)'}
					></span>
				</span>
				<span class="n">{c.count}</span>
			</li>
		{/each}
	</ul>
</section>

<style>
	.tools {
		display: flex;
		align-items: center;
		gap: 8px;
	}
	/* Cards clip their content; let the agent menu spill out of this one instead of being cut off. */
	.pl {
		overflow: visible;
	}
	/* The filter sits at the card's right edge: open the menu leftwards, under the button. */
	.tools :global(.fmenu) {
		left: auto;
		right: 0;
		max-height: var(--menu-max);
	}
	.tools.up :global(.fmenu) {
		top: auto;
		bottom: calc(100% + 4px);
	}
	.bars {
		list-style: none;
		margin: 0;
		padding: 14px;
		display: grid;
		gap: 10px;
	}
	li {
		display: grid;
		grid-template-columns: 96px 1fr 32px;
		align-items: center;
		gap: 10px;
	}
	.track {
		height: 10px;
		border-radius: 999px;
		background: var(--sunk);
		overflow: hidden;
	}
	.fill {
		display: block;
		height: 100%;
		border-radius: 999px;
		transition: width 0.25s ease;
	}
	.n {
		text-align: right;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}
</style>
