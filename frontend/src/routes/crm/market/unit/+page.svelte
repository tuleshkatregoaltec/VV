<script lang="ts">
import Download from 'lucide-svelte/icons/download'
import { page } from '$app/state'
import Empty from '$lib/crm/components/ui/Empty.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'
import Badges from '$lib/crm/market/Badges.svelte'
import { screen, UNITS } from '$lib/crm/market/data'
import Lab from '$lib/crm/market/Lab.svelte'
import LeadPicker from '$lib/crm/market/LeadPicker.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

/**
 * Unit report (UI only). Never shows an owner's name: only whether the owner is on the agency's
 * own file. DLD Circular 02-2026: a next step that contacts the owner shows only with a prior
 * deal on record.
 */
const s = screen('unit')
let sel = $state(
	UNITS.rows.some((u) => u.key === page.url.searchParams.get('unit'))
		? (page.url.searchParams.get('unit') as string)
		: 'bv'
)
let q = $state('')
/** Whether the agency's owner file is uploaded; a demo switch until Owners is read from the CRM. */
let fileUploaded = $state(true)

const list = $derived(
	UNITS.rows.filter(
		(u) => !q.trim() || `${u.name} ${u.where}`.toLowerCase().includes(q.trim().toLowerCase())
	)
)
const u = $derived(UNITS.rows.find((x) => x.key === sel) ?? UNITS.rows[0])
const fields = $derived.by(() => {
	const f: [string, string, boolean?][] = [
		['Where', u.where],
		['Owner', fileUploaded ? u.owner : UNITS.noFile, !fileUploaded],
		['Bought', u.bought],
		['Lease', u.lease],
		['Worth now', u.worth],
		['Gross yield', u.yld],
		['Building, 12 months', u.bldg],
		['Evidence', u.evidence]
	]
	if (fileUploaded && u.onFile)
		f.splice(2, 0, ['Record', u.prior ?? 'No prior deal on file', !u.prior])
	if (fileUploaded && u.onFile && u.next)
		f.push(['Next step', u.prior ? u.next : UNITS.noPrior, !u.prior])
	return f
})
const maxBar = $derived(Math.max(...u.bars))
</script>

<svelte:head><title>Unit report · Market</title></svelte:head>

<PageHeader title={s.label} facts="{u.name} · {u.where} · Example">
	{#snippet note()}<Badges status={s.status} tier={s.tier} />{/snippet}
	{#snippet right()}
		<LeadPicker kind="Unit report" label={u.name} primary />
		<button type="button" class="btn ghost" onclick={() => toast.show(`PDF ready · ${u.name} (example)`)}>
			<Download size={15} aria-hidden="true" />Download PDF
		</button>
	{/snippet}
</PageHeader>

<div class="mk-root">
	<div class="mk-gunit">
		<section class="card" aria-labelledby="mk-units">
			<div class="ch"><h2 id="mk-units">Units</h2><Lab src="ex" /></div>
			<div class="mk-pad"><input class="search" bind:value={q} placeholder="Building or unit number" aria-label="Find a unit" /></div>
			{#if list.length}
				<div class="mk-units" role="group" aria-label="Units">
					{#each list as r (r.key)}
						<button type="button" class="mk-unitbtn" aria-pressed={r.key === sel} onclick={() => (sel = r.key)}>
							<b>{r.name}</b><span>{r.where}</span>
						</button>
					{/each}
				</div>
			{:else}
				<Empty text="No unit found. Check the building name and unit number." />
			{/if}
			<label class="check mk-pad"><input type="checkbox" bind:checked={fileUploaded} /> Owner file uploaded (demo)</label>
		</section>

		<section class="card" aria-labelledby="mk-unit">
			<div class="ch"><h2 id="mk-unit">{u.name}</h2><Lab src="ex" /></div>
			<div class="cb">
				<dl class="mk-kv">
					{#each fields as [k, v, muted] (k)}<dt>{k}</dt><dd class={muted ? 'muted' : ''}>{v}</dd>{/each}
				</dl>
				{#if !fileUploaded}
					<p class="mk-note" style:margin-top="10px">The report never shows an owner's name. It says only whether the owner is on your agency's own file.</p>
				{/if}
			</div>
		</section>

		<section class="card" aria-labelledby="mk-pdf">
			<div class="ch"><h2 id="mk-pdf">PDF preview</h2><Lab src="ex" /></div>
			<div class="cb">
				<div class="mk-pdf" role="img" aria-label="PDF preview of the unit report for {u.name}">
					<div class="mk-pdf-h"><b><i>V</i>itevue</b><span>Unit report</span></div>
					<div class="mk-pdf-t">{u.name}</div>
					<div class="mk-pdf-s">{u.where}</div>
					{#each ['What you paid', "What it's worth", 'What it rents for', 'Lease ends'] as k, i (k)}
						<div class="mk-pdf-r"><span>{k}</span><b>{u.pdf[i]}</b></div>
					{/each}
					<div class="mk-pdf-c" aria-hidden="true">{#each u.bars as h, i (i)}<i style:height="{(h / maxBar) * 100}%"></i>{/each}</div>
					<div class="mk-pdf-f">Sources: DLD sales and Ejari leases, last 12 months.</div>
				</div>
				<div class="mk-row" style:margin-top="10px">
					<button type="button" class="btn ghost sm" onclick={() => toast.show('In build. It will send the PDF to your own Telegram chat, ready to forward.')}>Send to my phone</button>
					<span class="mk-tag mk-neu">In build</span>
				</div>
			</div>
		</section>
	</div>
</div>
