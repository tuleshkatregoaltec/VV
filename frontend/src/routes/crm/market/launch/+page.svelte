<script lang="ts">
import Download from 'lucide-svelte/icons/download'
import { page } from '$app/state'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Tabs from '$lib/crm/components/ui/Tabs.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { LAUNCH, num, screen } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import LeadPicker from '$lib/crm/market/LeadPicker.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Launch desk (UI only): developer ranking, their projects and each project's file. */
const s = screen('launch')
const DELIV = [
	{ id: 'any', label: 'Any' },
	{ id: '2026', label: '2026' },
	{ id: '2027', label: '2027' },
	{ id: '2028', label: '2028 and later' }
] as const
type Deliv = (typeof DELIV)[number]['id']
type St = 'any' | 'launching' | 'selling'
type FileTab = (typeof LAUNCH.fileTabs)[number]['id']

let dev = $state(0)
let proj = $state('a')
let tab = $state<FileTab>('br')
let delivery = $state<Deliv>('any')
let status = $state<St>(page.url.searchParams.get('status') === 'launching' ? 'launching' : 'any')

const projects = $derived(
	LAUNCH.projects.filter(
		(p) =>
			(status === 'any' || p.status === status) &&
			(delivery === 'any' || (delivery === '2028' ? p.year >= 2028 : String(p.year) === delivery))
	)
)
const p = $derived(projects.find((x) => x.key === proj) ?? projects[0])
const developer = $derived(LAUNCH.developers[dev])
</script>

<svelte:head><title>Launch desk · Market</title></svelte:head>

<PageHeader title={s.label} facts="1,024 projects · 40 markets · 13 launch dates · Platform demo, Sep 2026">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}<a class="btn ghost" href="/crm/matches">Open Matches in the CRM</a>{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="grid-3 mk-t3">
		{#each LAUNCH.counters as c (c.k)}
			{#if c.k === 'Launch dates'}
				<button type="button" class={['kpi', status === 'launching' && 'on']} aria-pressed={status === 'launching'} onclick={() => (status = status === 'launching' ? 'any' : 'launching')}>
					<span class="lbl">{c.k}</span><span class="v">{c.v}</span><span class="n">{c.n} · show launching</span>
				</button>
			{:else}
				<div class="kpi"><span class="lbl">{c.k}</span><span class="v">{c.v}</span><span class="n">{c.n}</span></div>
			{/if}
		{/each}
	</div>
	<div class="mk-labrow"><Lab src="demo" /><span>Counts across the platform</span></div>

	<div class="mk-gside">
		<section class="card" aria-labelledby="mk-devs">
			<div class="ch"><h2 id="mk-devs">Developer ranking</h2><Lab src="ex" /></div>
			<div role="group" aria-label="Developers">
				{#each LAUNCH.developers as d, i (d.name)}
					<button type="button" class="mk-dev" aria-pressed={i === dev} onclick={() => (dev = i)}>
						<span class="mk-rank">Rank {i + 1}</span><b>{d.name}</b><span class="mono">{d.score}</span>
					</button>
				{/each}
			</div>
		</section>

		<div class="mk-col">
			<section class="card" aria-labelledby="mk-projs">
				<div class="ch">
					<h2 id="mk-projs">{developer.name} <span class="facts">Rank {dev + 1} · score {developer.score}</span></h2>
					<Lab src="ex" />
				</div>
				<div class="cb mk-fbar">
					<Seg label="Delivery" items={[...DELIV]} value={delivery} onselect={(v) => (delivery = v)} />
					<Seg label="Status" items={[{ id: 'any', label: 'Any' }, { id: 'launching', label: 'Launching' }, { id: 'selling', label: 'Selling' }]} value={status} onselect={(v) => (status = v)} />
					<span class="count">{projects.length} projects</span>
				</div>
				{#if projects.length}
					<div class="tblwrap">
						<table class="tbl">
							<thead><tr><th>Project</th><th>Handover</th><th>Status</th><th class="r">Units available</th><th class="r">From AED</th></tr></thead>
							<tbody>
								{#each projects as x (x.key)}
									<tr class="row">
										<td><button type="button" class="linkbtn" aria-pressed={p?.key === x.key} onclick={() => (proj = x.key)}>{x.name}</button></td>
										<td>{x.handover}</td>
										<td><span class={['chip', x.status === 'launching' ? 'blue' : 'green']}>{x.status === 'launching' ? 'Launching' : 'Selling'}</span></td>
										<td class="r">{x.units}</td>
										<td class="r">{num(x.from)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<Empty text="No projects match these filters.">
						<button type="button" class="btn ghost sm" onclick={() => ((status = 'any'), (delivery = 'any'))}>Clear filters</button>
					</Empty>
				{/if}
			</section>

			<section class="card" aria-labelledby="mk-file">
				<div class="ch">
					<h2 id="mk-file">{p ? `${p.name} · project file` : 'Project file'}</h2>
					{#if p}<LeadPicker kind="Project" label="{developer.name} · {p.name}" />{/if}
				</div>
				<div class="cb">
					<Tabs variant="card" label="Project file" items={[...LAUNCH.fileTabs]} value={tab} onselect={(t) => (tab = t)} />
					{#if !p}
						<Empty text="No project selected. Clear the filters to see projects." />
					{:else if tab === 'br'}
						<div class="mk-docrow">
							<span class="mk-ficon">PDF</span>
							<span class="mk-tool-t"><b>Brochure, from the developer</b><span>Kept current per project</span></span>
							<button type="button" class="btn ghost sm" onclick={() => toast.show("Opens the developer's brochure (example)")}>Open</button>
						</div>
					{:else if tab === 'pp'}
						<div class="mk-plan" aria-hidden="true">{#each LAUNCH.plan as x (x.label)}<i style:flex={x.pct}></i>{/each}</div>
						<div class="mk-planl">{#each LAUNCH.plan as x (x.label)}<div style:flex={x.pct}><b>{x.pct}%</b><span>{x.label}</span></div>{/each}</div>
					{:else if tab === 'cs'}
						<dl class="mk-kv">{#each LAUNCH.slip as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}</dl>
						<button type="button" class="btn ghost sm" style:margin-top="10px" onclick={() => toast.show(`Commission slip ready · ${p.name} (example)`)}>
							<Download size={14} aria-hidden="true" />Download slip
						</button>
					{:else if tab === 'ua'}
						{@const rows = LAUNCH.units[p.key] ?? []}
						<table class="tbl">
							<thead><tr><th>Type</th><th class="r">Available</th><th class="r">From, AED</th></tr></thead>
							<tbody>
								{#each rows as [t, n, from] (t)}<tr><td>{t}</td><td class="r">{n}</td><td class="r">{num(from)}</td></tr>{/each}
								<tr class="tot"><td><b>Total</b></td><td class="r"><b>{rows.reduce((a, r) => a + r[1], 0)}</b></td><td></td></tr>
							</tbody>
						</table>
					{:else if tab === 'rf'}
						<div class="mk-thumbs">{#each LAUNCH.renders as r (r)}<span>{r}</span>{/each}</div>
					{:else if tab === 'sn'}
						<dl class="mk-kv">{#each LAUNCH.site as [k, v] (k)}<dt>{k}</dt><dd>{v}</dd>{/each}</dl>
					{:else}
						<dl class="mk-kv"><dt>{LAUNCH.irr.label}</dt><dd><b>{LAUNCH.irr.value}</b></dd></dl>
						<p class="mk-note" style:margin-top="8px">{LAUNCH.irr.line}</p>
					{/if}
				</div>
			</section>
		</div>
	</div>
</div>
