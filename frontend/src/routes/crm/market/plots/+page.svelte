<script lang="ts">
import Download from 'lucide-svelte/icons/download'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { FEAS, PLOTS, screen } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import LeadPicker from '$lib/crm/market/LeadPicker.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Plots and feasibility (UI only): plot valuations on a schematic plan and the model's tabs. */
const s = screen('plots')
type Mode = (typeof FEAS.modes)[number]['id']
type FTab = (typeof FEAS.tabs)[number]['id']
let plot = $state('p1')
let mode = $state<Mode>('rent')
let tab = $state<FTab>('sum')

const pl = $derived(PLOTS.rows.find((r) => r.key === plot) ?? PLOTS.rows[0])
const t = $derived(FEAS.tabs.find((x) => x.id === tab) ?? FEAS.tabs[0])
const modelled = $derived(mode === FEAS.modelled)
</script>

<svelte:head><title>Plots and feasibility · Market</title></svelte:head>

<PageHeader title={s.label} facts="{FEAS.summary.facts} · Platform demo, Sep 2026">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}
		<button type="button" class="btn ghost" onclick={() => toast.show(modelled ? `Workbook exported · ${FEAS.tabs.length} tabs (example)` : 'No model to export for this mode')}>
			<Download size={15} aria-hidden="true" />Export to Excel
		</button>
	{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="mk-gplots">
		<section class="card" aria-labelledby="mk-plots">
			<div class="ch">
				<h2 id="mk-plots">Plots <span class="facts">Plot valuations</span></h2>
				<span class="mk-row"><Lab src="ex" /><LeadPicker kind="Plot" label={pl.label} /></span>
			</div>
			<div class="cb mk-stack">
				<svg class="mk-plotmap" viewBox="0 0 370 290" aria-hidden="true" focusable="false">
					{#each PLOTS.roads as r, i (i)}<rect class="mk-road" x={r[0]} y={r[1]} width={r[2]} height={r[3]}></rect>{/each}
					{#each PLOTS.blocks as r, i (i)}<rect class="mk-block" x={r[0]} y={r[1]} width={r[2]} height={r[3]}></rect>{/each}
					{#each PLOTS.rows as r (r.key)}
						<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
						<g class={['mk-pl', r.key === plot && 'on']} onclick={() => (plot = r.key)}>
							<rect x={r.x} y={r.y} width={r.w} height={r.h}></rect>
							<text x={r.x + r.w / 2} y={r.y + r.h / 2 + 5}>{r.label}</text>
						</g>
					{/each}
				</svg>
				<Seg label="Plot" items={PLOTS.rows.map((r) => ({ id: r.key, label: r.label }))} value={plot} onselect={(v) => (plot = v)} />
				<dl class="mk-kv">{#each pl.fields as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}</dl>
			</div>
		</section>

		<section class="card" aria-labelledby="mk-feas">
			<div class="ch">
				<h2 id="mk-feas">Feasibility <span class="mk-tier">Feasibility · Tier 3</span></h2>
				<Seg label="Mode" items={[...FEAS.modes]} value={mode} onselect={(v) => (mode = v)} />
			</div>
			<div class="cb">
				<Tabs variant="card" label="Feasibility tabs" items={[...FEAS.tabs]} value={tab} onselect={(v) => (tab = v)} />
				{#if !modelled}
					<Empty text="No model run for this mode. Example data has a build-to-rent model only.">
						<button type="button" class="btn ghost sm" onclick={() => (mode = 'rent')}>Show build to rent</button>
					</Empty>
				{:else if t.id === 'sum'}
					<dl class="mk-kv">
						{#each FEAS.summary.rows as [k, v] (k)}<dt>{k}</dt><dd><b>{v}</b></dd>{/each}
						<dt>{FEAS.summary.irr[0]}</dt><dd>{FEAS.summary.irr[1]}</dd>
					</dl>
					<div class="mk-labrow" style:margin-top="10px"><Lab src="demo" /><span>{FEAS.summary.line}</span></div>
				{:else}
					<p>{t.line}</p>
				{/if}
			</div>
		</section>
	</div>
</div>
