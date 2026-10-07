<script lang="ts">
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type { ImportPreview } from '../../api/types'
import { fmt } from '../../format'
import { panel } from '../../stores/panel.svelte'
import { errorText, write } from '../../write'
import Panel from '../ui/Panel.svelte'
import Seg from '../ui/Seg.svelte'

/**
 * Import a file: Owners or Leads, areas, CSV → preview → import. A manager imports directly
 * (owners are checked against DLD; leads land in the Inbox); an agent is told to send the file
 * to their manager (approval requests are open question 9). The backend reads the file and
 * picks the columns; this screen only shows what it found.
 */
let kind = $state<'Owners' | 'Leads'>('Owners')
let areas = $state('')
let file = $state<File | null>(null)
let preview = $state<ImportPreview | null>(null)
let problem = $state('')
let reading = $state(false)
let drag = $state(false)
let input: HTMLInputElement | undefined = $state()

async function read(f: File | undefined) {
	if (!f) return
	file = f
	preview = null
	problem = ''
	reading = true
	try {
		preview = await crm.imports.preview(f, kind)
		problem = preview.problem ?? ''
	} catch (e) {
		problem = errorText(e)
	} finally {
		reading = false
	}
}

async function send() {
	if (!file || !preview) return
	const f = file
	const rows = preview.rows
	const r = await write({
		call: () => crm.imports.create(f, kind, areas.trim()),
		success: `Imported · ${fmt(rows)} rows`,
		event: 'import_requested'
	})
	if (r) {
		panel.closeAll()
		await goto(kind === 'Leads' ? '/crm/inbox' : '/crm/owners')
	}
}
</script>

<Panel kicker="New" title="Import a file" sub="Managers import · owners are checked against DLD, leads go to the Inbox">
	<div class="form">
		<div class="fld">
			<span class="fl">What is in the file</span>
			<Seg
				label="What is in the file"
				items={[
					{ id: 'Owners', label: 'Owners' },
					{ id: 'Leads', label: 'Leads' }
				]}
				value={kind}
				onselect={(k) => (kind = k)}
			/>
		</div>
		<div class="fld">
			<label for="imp-areas">Areas</label>
			<input id="imp-areas" placeholder="JVC, Dubai Marina" bind:value={areas} />
		</div>
		<input
			bind:this={input}
			type="file"
			accept=".csv,text/csv"
			hidden
			aria-hidden="true"
			tabindex="-1"
			onchange={() => read(input?.files?.[0])}
		/>
		<button
			type="button"
			class={['drop', drag && 'drag']}
			onclick={() => input?.click()}
			ondragover={(e) => {
				e.preventDefault()
				drag = true
			}}
			ondragleave={() => (drag = false)}
			ondrop={(e) => {
				e.preventDefault()
				drag = false
				read(e.dataTransfer?.files[0])
			}}
		>
			<b>{file ? file.name : 'Drop a CSV here'}</b>
			<span>{kind === 'Owners' ? 'name, mobile, community, building, unit number' : 'name, phone or mobile, area, budget'}</span>
			<span class="btn ghost sm">{file ? 'Choose another CSV' : 'Choose a CSV'}</span>
		</button>

		{#if reading}<div class="small muted">Reading the file…</div>{/if}
		{#if problem}<div class="notice" role="alert">{problem}</div>{/if}

		{#if preview}
			<section class="sec">
				<h3>{fmt(preview.rows)} rows · {preview.file}</h3>
				<div class="tblwrap boxed">
					<table class="tbl">
						<thead>
							<tr>
								<th>Name{preview.columns.name ? ` (${preview.columns.name})` : ''}</th>
								<th>Phone{preview.columns.phone ? ` (${preview.columns.phone})` : ''}</th>
								<th>Budget</th>
								<th>Area</th>
							</tr>
						</thead>
						<tbody>
							{#each preview.sample as row, i (i)}
								<tr>
									<td>{row.name || '—'}</td>
									<td class="mono small" data-label="Phone">{row.phone || '—'}</td>
									<td data-label="Budget">{row.budget || '—'}</td>
									<td data-label="Area">{row.area || '—'}</td>
								</tr>
							{/each}
						</tbody>
					</table>
				</div>
				{#if preview.rows > 5}<div class="small muted">and {fmt(preview.rows - 5)} more</div>{/if}
			</section>
			{#if !preview.problem}
				<div>
					<button type="button" class="btn" onclick={send}>
						Import {fmt(preview.rows)} rows
					</button>
				</div>
			{/if}
		{/if}
	</div>
</Panel>
