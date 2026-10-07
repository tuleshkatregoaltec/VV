<script lang="ts">
import Download from 'lucide-svelte/icons/download'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Seg from '$lib/crm/components/ui/Seg.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import {
	AS_OF,
	addDays,
	fDay,
	num,
	type Reg,
	screen,
	TX,
	type TxKind,
	type TxRow,
	type TxUse
} from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/** Transactions (UI only, example rows): filters, sortable table, export panel. */
const s = screen('tx')
const REG_LABEL = Object.fromEntries(TX.regs.map((r) => [r.id, r.label])) as Record<Reg, string>
type Col = 'date' | 'project' | 'building' | 'unit' | 'type' | 'sqm' | 'price' | 'psm' | 'reg'
const COLS: [Col, string, boolean][] = [
	['date', 'Date', false],
	['project', 'Project', false],
	['building', 'Building', false],
	['unit', 'Unit', false],
	['type', 'Use and type', false],
	['sqm', 'Sqm', true],
	['price', 'Price AED', true],
	['psm', 'Per sqm AED', true],
	['reg', 'Registration', false]
]

let kind = $state<TxKind>('sale')
let use = $state<TxUse>('commercial')
let period = $state(365)
let regs = $state<Record<Reg, boolean>>({
	deed: true,
	oqood: true,
	gift: true,
	mortgage: true,
	ejari: true
})
let sort = $state<{ col: Col; dir: 'asc' | 'desc' }>({ col: 'date', dir: 'desc' })
let exportOpen = $state(false)
let periodOpen = $state(false)
let cols = $state<Record<string, boolean>>(Object.fromEntries(TX.cols.map((c) => [c.id, true])))

function useType(r: TxRow) {
	return `${r.use === 'commercial' ? 'Commercial' : 'Residential'} · ${r.type}${r.kind === 'rent' ? ' · rent' : ''}`
}
function key(r: TxRow): string | number {
	if (sort.col === 'type') return useType(r)
	if (sort.col === 'reg') return REG_LABEL[r.reg]
	if (sort.col === 'unit') return ''
	return r[sort.col] ?? ''
}
const rows = $derived.by(() => {
	const since = addDays(AS_OF, -period)
	const dir = sort.dir === 'asc' ? 1 : -1
	return TX.rows
		.filter((r) => r.kind === kind && r.use === use && r.date >= since && regs[r.reg])
		.sort((a, b) => {
			const x = key(a)
			const y = key(b)
			return (x < y ? -1 : x > y ? 1 : a.n - b.n) * dir
		})
})
const isDemo = $derived(
	kind === TX.demoCount.kind &&
		use === TX.demoCount.use &&
		period === TX.demoCount.period &&
		Object.values(regs).every(Boolean)
)
const countText = $derived(
	isDemo ? `${num(TX.demoCount.n)} matching` : `${rows.length} example rows`
)
const periodLabel = $derived(TX.periods.find((p) => p.days === period)?.label ?? '')
const colsOn = $derived(Object.values(cols).filter(Boolean).length)

function sortBy(c: Col) {
	if (sort.col === c) sort.dir = sort.dir === 'asc' ? 'desc' : 'asc'
	else sort = { col: c, dir: ['date', 'sqm', 'price', 'psm'].includes(c) ? 'desc' : 'asc' }
}
function clear() {
	kind = 'sale'
	use = 'commercial'
	period = 365
	regs = { deed: true, oqood: true, gift: true, mortgage: true, ejari: true }
}
</script>

<svelte:head><title>Transactions · Market</title></svelte:head>

<PageHeader
	title={s.label}
	facts="{countText} · {kind === 'sale' ? 'Sales' : 'Rentals'} · {use === 'commercial' ? 'Commercial' : 'Residential'} · {periodLabel}"
>
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}
		<button type="button" class="btn ghost" aria-expanded={exportOpen} onclick={() => (exportOpen = !exportOpen)}>
			<Download size={15} aria-hidden="true" />Export
		</button>
	{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="mk-fbar">
		<Seg label="Kind" items={[{ id: 'sale', label: 'Sales' }, { id: 'rent', label: 'Rentals' }]} value={kind} onselect={(v) => (kind = v)} />
		<Seg label="Use" items={[{ id: 'residential', label: 'Residential' }, { id: 'commercial', label: 'Commercial' }]} value={use} onselect={(v) => (use = v)} />
		<span class="mk-pick">
			<button type="button" class="btn ghost" aria-haspopup="menu" aria-expanded={periodOpen} onclick={() => (periodOpen = !periodOpen)}>{periodLabel} ▾</button>
			{#if periodOpen}
				<div class="mk-menu left" role="menu" aria-label="Period">
					{#each TX.periods as p (p.days)}
						<button type="button" class="mk-mi" role="menuitemradio" aria-checked={period === p.days} onclick={() => ((period = p.days), (periodOpen = false))}>
							{period === p.days ? '✓' : ''} {p.label}
						</button>
					{/each}
				</div>
			{/if}
		</span>
		<span class="mk-row" role="group" aria-label="Registration">
			<span class="muted small">Registration</span>
			{#each TX.regs as r (r.id)}
				<button type="button" class="chip mk-tog" aria-pressed={regs[r.id]} onclick={() => (regs[r.id] = !regs[r.id])}>{r.label}</button>
			{/each}
		</span>
		<span class="count">{countText} <Lab src={isDemo ? 'demo' : 'ex'} /></span>
	</div>

	{#if exportOpen}
		<section class="card" aria-labelledby="mk-exp">
			<div class="ch">
				<h2 id="mk-exp">Export <span class="facts">{countText} · {colsOn} of {TX.cols.length} columns</span></h2>
				<button type="button" class="btn plain sm" onclick={() => (exportOpen = false)}>Close</button>
			</div>
			<div class="cb mk-stack">
				<span class="mk-row" role="group" aria-label="Columns">
					{#each TX.cols as c (c.id)}
						<button type="button" class="chip mk-tog" aria-pressed={cols[c.id]} disabled={cols[c.id] && colsOn === 1} onclick={() => (cols[c.id] = !cols[c.id])}>{c.label}</button>
					{/each}
				</span>
				<div class="mk-row">
					<button type="button" class="btn" onclick={() => toast.show(`Export ready · ${countText} · Excel (example)`)}>Export to Excel</button>
					<button type="button" class="btn ghost" onclick={() => toast.show(`Export ready · ${countText} · CSV (example)`)}>Export to CSV</button>
				</div>
				<p class="mk-note">Up to {num(TX.exportLimit)} rows a pull. Market data only; CRM records are not exported.</p>
			</div>
		</section>
	{/if}

	<section class="card" aria-labelledby="mk-rows">
		<div class="ch"><h2 id="mk-rows">Rows <span class="facts">{rows.length} example rows shown</span></h2><Lab src="ex" /></div>
		{#if rows.length}
			<div class="tblwrap">
				<table class="tbl">
					<thead>
						<tr>
							{#each COLS as [c, label, right] (c)}
								<th class={right ? 'r' : ''} aria-sort={sort.col === c ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
									<button type="button" class="mk-th" onclick={() => sortBy(c)}>
										{label}<span class="mk-sortmark" aria-hidden="true">{sort.col === c ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}</span>
									</button>
								</th>
							{/each}
						</tr>
					</thead>
					<tbody>
						{#each rows as r (r.n)}
							<tr>
								<td class="nowrap">{fDay(r.date)}</td>
								<td>{r.project}</td>
								<td>{r.building ?? '—'}</td>
								<td class="muted" title="Unit numbers: not shown until the source is confirmed">—</td>
								<td>{useType(r)}</td>
								<td class="r">{r.sqm.toLocaleString('en-US', { maximumFractionDigits: 2 })}</td>
								<td class="r">{num(r.price)}{r.kind === 'rent' ? ' a year' : ''}</td>
								<td class="r">{num(r.psm)}</td>
								<td>{REG_LABEL[r.reg]}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else}
			<Empty text={kind === 'rent' && use === 'commercial' ? 'No transactions match. Example data has no commercial rentals.' : 'No transactions match these filters.'}>
				<button type="button" class="btn ghost sm" onclick={clear}>Clear filters</button>
			</Empty>
		{/if}
	</section>
	<p class="mk-note">Every registered sale and rental: DLD title deeds, Oqood, gifts and mortgages, plus Ejari leases. Unit numbers are not shown until the source is confirmed.</p>
</div>
