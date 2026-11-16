<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { goto } from '$app/navigation'
import { crm } from '../../api'
import type {
	ImportAssignment,
	ImportPreview,
	OwnerFilePreview,
	OwnerImportResult
} from '../../api/types'
import { fmt } from '../../format'
import {
	importIsActive,
	importProgressNotice,
	importUploadMessage,
	ownerImportNotice
} from '../../importStatus'
import { fieldChecklist, fieldLabel } from '../../ownerImportReport'
import { crmQueries } from '../../queries'
import { watchQueuedImport } from '../../stores/imports.svelte'
import { panel } from '../../stores/panel.svelte'
import { errorText, write } from '../../write'
import AssignmentPicker from '../ui/AssignmentPicker.svelte'
import Kv from '../ui/Kv.svelte'
import Panel from '../ui/Panel.svelte'
import Seg from '../ui/Seg.svelte'

/**
 * Import a file: Owners or Leads, CSV or XLSX → preview → import (owners are matched to sales;
 * leads land in the Inbox). A leads import always says who handles the new leads. An agent
 * imports only for themselves: the leads are assigned to them and there is nothing to choose. A
 * manager or organization administrator picks one agent they may assign to, the routing rules,
 * the team's shared pool (the first agent to log contact takes each lead), or nobody yet, and
 * which of their teams owns what nobody receives. A manager imports an owners file directly; an
 * agent's goes to their team's supervisor for approval first. The backend reads the file and
 * picks the columns; this screen only shows what it found. From the Owners page it imports owners only.
 *
 * An owners file is read in the browser first, then queued for background processing.
 * Upload acceptance and completed row results are shown separately. The preview speaks in our
 * fields (found or not found) and never prints the file's own column headers. Renaming and
 * deleting a file are on its report.
 */
let { ownersOnly = false, leadsOnly = false }: { ownersOnly?: boolean; leadsOnly?: boolean } =
	$props()
let kind = $state<'Owners' | 'Leads'>('Owners')
let areas = $state('')
/** Owners: the name of the import and its saved list; empty uses the file name. */
let listName = $state('')
let file = $state<File | null>(null)
let preview = $state<ImportPreview | null>(null)
let ownerPreview = $state<OwnerFilePreview | null>(null)
let result = $state<OwnerImportResult | null>(null)
/** Owners: an agent in several teams picks the team whose supervisor approves the file. */
let teamChoice = $state('')
/** An agent's owners file was sent to their team's supervisor for approval. */
let requested = $state(false)
let problem = $state('')
let reading = $state(false)
let sending = $state(false)
let drag = $state(false)
let input: HTMLInputElement | undefined = $state()

const owners = $derived(ownersOnly || (!leadsOnly && kind === 'Owners'))
/** Who may import leads and to whom: the server decides, not the display role. */
const scope = createQuery(() => crmQueries.assignmentScope())
const canImportLeads = $derived(scope.data?.capabilities.can_import ?? false)
/** Managers and administrators choose who gets the leads; an agent's go to themselves. */
const canDistribute = $derived(scope.data?.capabilities.can_assign ?? false)
const ownerTeams = $derived(scope.data?.my_teams ?? [])
const ownerTeamFor = $derived(ownerTeams.length === 1 ? ownerTeams[0].id : teamChoice)
const ownerTeamMissing = $derived(
	owners && !canDistribute && ownerTeams.length > 1 && !ownerTeamFor
)
/** Leads: who handles them, from the shared picker (null while the choice is incomplete). */
let assignment = $state<ImportAssignment | null>(null)

async function openReport(id: number) {
	panel.closeAll()
	await goto(`/crm/owners/imports/${id}`)
}

/** "Project", "Project 2": two columns can feed one field (the second is read when the first is blank). */
function numbered(labels: string[]) {
	const seen = new Map<string, number>()
	return labels.map((label) => {
		const n = (seen.get(label) ?? 0) + 1
		seen.set(label, n)
		return n === 1 ? label : `${label} ${n}`
	})
}

/** Our field names for the columns the backend reads, with the sample values under them. */
function readColumns(p: OwnerFilePreview) {
	const index = (p.fields ?? []).flatMap((f, i) => (f ? [i] : []))
	return {
		headers: numbered(index.map((i) => fieldLabel(p.fields?.[i] ?? ''))),
		rows: p.sample.slice(0, 3).map((row) => index.map((i) => row[i] ?? '')),
		checklist: fieldChecklist(
			(p.fields ?? []).filter((f): f is string => Boolean(f)),
			false
		)
	}
}
const rows = $derived(owners ? (ownerPreview?.rows ?? 0) : (preview?.rows ?? 0))
const ready = $derived(
	owners
		? ownerPreview && !ownerPreview.problem
		: preview && !preview.problem && canImportLeads && assignment !== null
)

function reset() {
	file = null
	preview = null
	ownerPreview = null
	result = null
	requested = false
	problem = ''
	if (input) input.value = ''
}

function size(bytes: number): string {
	return bytes < 1024 * 1024
		? `${Math.max(1, Math.round(bytes / 1024))} KB`
		: `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function read(f: File | undefined) {
	if (!f) return
	reset()
	file = f
	reading = true
	try {
		if (owners) {
			ownerPreview = await crm.imports.previewOwners(f)
			problem = ownerPreview.problem ?? ''
		} else {
			preview = await crm.imports.preview(f)
			problem = preview.problem ?? ''
		}
	} catch (e) {
		problem = errorText(e)
	} finally {
		reading = false
	}
}

async function send() {
	if (!file || !ready || sending) return
	const f = file
	if (!owners) {
		const policy = assignment
		if (!policy) return
		sending = true
		const r = await write({
			domain: 'imports',
			call: () => crm.imports.create(f, areas.trim(), policy),
			success: ({ data }) => importUploadMessage(data.jobStatus, data.rows),
			event: 'import_requested'
		})
		sending = false
		if (r) {
			if (importIsActive(r.data.jobStatus)) watchQueuedImport(r.data.id)
			panel.closeAll()
			await goto('/crm/inbox')
		}
		return
	}
	if (ownerTeamMissing) return
	sending = true
	if (!canDistribute) {
		// Agents send owner files to their team's supervisor; nothing is imported until approved.
		const sent = await write({
			domain: 'imports',
			call: () => crm.imports.requestOwners(f, listName, ownerTeamFor || undefined),
			success: 'Sent for approval',
			undoable: false,
			event: 'import_requested'
		})
		sending = false
		if (sent) requested = true
		return
	}
	const r = await write({
		domain: 'imports',
		call: () => crm.imports.importOwners(f, listName),
		success: ({ data }) =>
			importUploadMessage(data.status, data.summary.candidateRows, data.alreadyImported),
		event: 'import_requested'
	})
	sending = false
	if (r) {
		result = r.data
		if (importIsActive(r.data.status)) watchQueuedImport(`O${r.data.id}`)
	}
}
</script>

<Panel
	kicker="New"
	title={owners ? 'Import an owner file' : 'Import a file'}
	footer={result ? done : undefined}
>
	<div class="form">
		{#if requested}
			<div class="notice" role="status">
				Sent for approval. The selected team’s supervisor or an organisation administrator must
				approve before the owners are imported; if you have no team, an administrator approves.
				You can follow it under Owner file and import requests.
			</div>
		{:else if result}
			{@const s = result.summary}
			{@const replayNotice = ownerImportNotice(result)}
			{#if replayNotice}<div class="notice" role="status">{replayNotice}</div>{/if}
			{#if result.status === 'failed'}
				<div class="notice" role="alert">
					The import of this file failed (import #{result.id}). Fix the file and upload it again.
				</div>
			{:else if importIsActive(result.status)}
				<div class="notice" role="status">{importProgressNotice(result.status)}</div>
			{:else}
				<section class="sec">
					<h3>{result.name}</h3>
					{#if result.match}
						{@const m = result.match}
						<div class="kv result">
							<Kv k="Units identified" v={fmt(m.total)} />
							<Kv k="Units mapped" v={fmt(m.headline.units)} o={`${m.headline.percent}% coverage`} />
							<Kv k="Rows to review" v={fmt(m.review.rows)} />
							{#if m.sales}<Kv k="Sales matched" v={fmt(m.sales.total)} />{/if}
						</div>
					{:else}
						<p class="small muted">{fmt(s.candidateRows)} rows kept from {fmt(s.totalRows)}.</p>
					{/if}
					<details>
						<summary>Processing details</summary>
						<div class="kv">
							<Kv k="Rows in the file" v={fmt(s.totalRows)} />
							<Kv k="Rows kept" v={fmt(s.candidateRows)} o={s.duplicatesCollapsed ? `${fmt(s.duplicatesCollapsed)} duplicates merged` : ''} />
							{#if s.distinctProperties !== null}<Kv k="Properties" v={fmt(s.distinctProperties)} />{/if}
							<Kv k="With a phone or email" v={fmt(s.validContacts)} />
							<Kv k="Contactable candidates" v={fmt(s.contactReady)} />
							<Kv k="Current owners" v={fmt(s.verified)} />
							<Kv k="Possible owners" v={fmt(s.probable)} />
							<Kv k="Property found, owner unknown" v={fmt(s.unitLinked)} />
							<Kv k="Former owners" v={fmt(s.former)} />
							<Kv k="Conflicting records" v={fmt(s.conflicting)} />
							<Kv k="Not matched" v={fmt(s.notMatched)} />
							<Kv k="Rental opportunities" v={fmt(s.rentalOpportunities)} />
						</div>
					</details>
				</section>
			{/if}
		{:else}
			{#if !ownersOnly && !leadsOnly}
				<div class="fld">
					<span class="fl">What is in the file</span>
					<Seg
						label="What is in the file"
						items={[
							{ id: 'Owners', label: 'Owners' },
							{ id: 'Leads', label: 'Leads' }
						]}
						value={kind}
						onselect={(k) => {
							kind = k
							reset()
						}}
					/>
				</div>
			{/if}
			{#if !owners}
				<div class="fld">
					<label for="imp-areas">Areas</label>
					<input id="imp-areas" placeholder="JVC, Dubai Marina" bind:value={areas} />
				</div>
			{/if}
			<input
				bind:this={input}
				type="file"
				accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
				hidden
				aria-hidden="true"
				tabindex="-1"
				onchange={() => read(input?.files?.[0])}
			/>
			<button
				type="button"
				class={['drop', drag && 'drag']}
				disabled={sending}
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
				<b>{file ? file.name : 'Drop a CSV or XLSX file here'}</b>
				<span class="btn ghost sm">{file ? 'Choose another file' : 'Choose a file'}</span>
			</button>

			{#if owners}
				<div class="fld">
					<label for="imp-list">List name</label>
					<input
						id="imp-list"
						maxlength="200"
						placeholder={file ? file.name.replace(/\.[^.]+$/, '') : 'Downtown owners, July'}
						bind:value={listName}
						disabled={sending}
					/>
				</div>
			{/if}
			{#if reading}<div class="small muted">Reading the file…</div>{/if}
			{#if problem}<div class="notice" role="alert">{problem}</div>{/if}

			{#if owners && ownerPreview && !ownerPreview.problem}
				{@const p = ownerPreview}
				{@const cols = readColumns(p)}
				{@const used = p.fields?.filter(Boolean).length ?? 0}
				<section class="sec">
					<h3>
						{fmt(p.rows)} rows · {p.file} · {size(p.size)}{p.sheets > 1 ? ` · ${p.sheets} sheets` : ''}
					</h3>
					{#if p.fields}
						<p class="small muted">
							{used} of {p.headers.length} columns read{p.headers.length - used
								? ` · ${p.headers.length - used} ${p.readAtImport ? 'assigned at import' : 'unused'}`
								: ''}{p.sheets > 1 ? ' · first sheet shown' : ''}
						</p>
						<ul class="found" aria-label="Fields in the file">
							{#each cols.checklist as f (f.field)}
								<li class={['fd', f.found && 'on']}>{f.field}<span>{f.found ? 'found' : 'not found'}</span></li>
							{/each}
						</ul>
						{#if cols.headers.length}
							<div class="tblwrap boxed cols">
								<table class="tbl">
									<thead>
										<tr>
											{#each cols.headers as h, i (i)}<th>{h}</th>{/each}
										</tr>
									</thead>
									<tbody>
										{#each cols.rows as row, i (i)}
											<tr>
												{#each row as cell, j (j)}
													<td data-label={cols.headers[j]}>{cell || '—'}</td>
												{/each}
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					{:else}
						<p class="small muted">{p.headers.length} columns found</p>
					{/if}
					{#if p.rows > 3}<div class="small muted">and {fmt(p.rows - 3)} more rows</div>{/if}
				</section>
			{:else if !owners && preview}
				<section class="sec">
					<h3>{fmt(preview.rows)} rows · {preview.file}</h3>
					<div class="tblwrap boxed">
						<table class="tbl">
							<thead>
								<tr>
									<th>Name</th>
									<th>Phone</th>
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
			{/if}

			{#if !owners && preview && !preview.problem && canImportLeads}
				<AssignmentPicker bind:assignment disabled={sending} id="imp" />
			{/if}

			{#if owners && !canDistribute && ownerTeams.length > 1}
				<div class="fld">
					<label for="owner-team">Team that owns this owner file</label>
					<select id="owner-team" bind:value={teamChoice} disabled={sending}>
						<option value="">Choose a team</option>
						{#each ownerTeams as t (t.id)}<option value={t.id}>{t.name}</option>{/each}
					</select>
					<div class="small muted">This team's supervisor or an organisation administrator approves it.</div>
				</div>
			{/if}

			{#if ready}
				<div class="acts">
					<button type="button" class="btn ghost" disabled={sending} onclick={() => panel.closeAll()}>Cancel</button>
					<button type="button" class="btn" disabled={sending || ownerTeamMissing} onclick={send}>
						{sending ? 'Uploading…' : `Import ${fmt(rows)} rows`}
					</button>
				</div>
				{#if sending && owners}
					<div class="small muted">Uploading the file. Once accepted, processing continues in the background.</div>
				{/if}
			{/if}
		{/if}
	</div>

</Panel>

{#snippet done()}
	<button type="button" class="btn" onclick={() => panel.closeAll()}>Done</button>
	{#if result}
		{@const id = result.id}
		<button type="button" class="btn ghost" onclick={() => openReport(id)}>Open report</button>
	{/if}
	<button
		type="button"
		class="btn ghost"
		onclick={() => {
			reset()
			listName = ''
		}}
	>
		Import another file
	</button>
{/snippet}

<style>
	summary { cursor: pointer; color: var(--text2); font-size: 12.5px; }
	.acts {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
	}
	.cols {
		overflow-x: auto;
	}
	.cols th,
	.cols td {
		white-space: nowrap;
	}
	.cols th {
		vertical-align: top;
	}
	.found {
		display: flex;
		flex-wrap: wrap;
		gap: 0.3rem;
		list-style: none;
		margin: 0.5rem 0;
		padding: 0;
	}
	.fd {
		display: inline-flex;
		gap: 0.4rem;
		padding: 0.15rem 0.5rem;
		border: 1px solid var(--sep);
		border-radius: 999px;
		font-size: 12.5px;
		color: var(--text2);
	}
	.fd.on {
		color: var(--text);
	}
	.fd.on span {
		color: var(--green);
	}
</style>
