<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import ArrowRight from 'lucide-svelte/icons/arrow-right'
import ChevronDown from 'lucide-svelte/icons/chevron-down'
import ChevronUp from 'lucide-svelte/icons/chevron-up'
import InboxIcon from 'lucide-svelte/icons/inbox'
import Info from 'lucide-svelte/icons/info'
import Languages from 'lucide-svelte/icons/languages'
import Layers from 'lucide-svelte/icons/layers'
import MapPin from 'lucide-svelte/icons/map-pin'
import Pencil from 'lucide-svelte/icons/pencil'
import Plus from 'lucide-svelte/icons/plus'
import Target from 'lucide-svelte/icons/target'
import Trash from 'lucide-svelte/icons/trash-2'
import X from 'lucide-svelte/icons/x'
import { tick } from 'svelte'
import type {
	RoutingCondition,
	RoutingRuleResponse,
	RoutingRuleWrite
} from '$lib/api/generated/hey-api/types.gen'
import { crm } from '../../api'
import { personName } from '../../assignment'
import { SOURCE_OPTIONS } from '../../config'
import { crmQueries } from '../../queries'
import { write } from '../../write'
import ChipsInput from '../ui/ChipsInput.svelte'
import QueryView from '../ui/QueryView.svelte'
import Seg from '../ui/Seg.svelte'

/**
 * Lead routing: ordered rules that send newly imported leads to one person. The first rule that
 * matches wins; a lead no rule matches waits unassigned. Rules only route imports made after
 * they change; existing leads never move. Administrators edit every rule; managers edit their
 * own teams' rules. A rule can also rotate: when the person holding a lead neither logs contact
 * nor changes its stage in time, it moves to the next person listed, then to the team's pool.
 */
let { editable }: { editable: boolean } = $props()

const rules = createQuery(() => crmQueries.routingRules())
const scope = createQuery(() => crmQueries.assignmentScope())

type Field = RoutingCondition['field']
const FIELDS: { id: Field; label: string }[] = [
	{ id: 'area', label: 'Area' },
	{ id: 'intent', label: 'Intent' },
	{ id: 'source', label: 'Source' },
	{ id: 'language', label: 'Language' }
]
const fieldLabel = (f: Field) => FIELDS.find((x) => x.id === f)?.label ?? f
const INTENTS = [
	{ value: 'buy', label: 'Buy' },
	{ value: 'rent', label: 'Rent' },
	{ value: 'sell', label: 'Sell' },
	{ value: 'let', label: 'Let' }
]
/** The CRM's lead sources, plus "Imported": what a file with no Source column records. */
const SOURCES = [...SOURCE_OPTIONS.map((o) => o.label), 'Imported'].map((s) => ({
	value: s,
	label: s
}))
const OPTIONS: Record<Field, { value: string; label: string }[]> = {
	area: [],
	intent: INTENTS,
	source: SOURCES,
	language: []
}
const PLACEHOLDER: Record<Field, string> = {
	area: 'Type an area, e.g. JVC, and press Enter',
	intent: 'Buy, rent, sell or let',
	source: 'Pick or type a source, as written in your file',
	language: 'Type a language as written in your file, e.g. Hindi'
}
const valueLabel = (f: Field, v: string) => OPTIONS[f].find((o) => o.value === v)?.label ?? v

type Draft = {
	id: number | null
	revision: number
	name: string
	team_id: string
	user_id: string
	match_mode: 'all' | 'any'
	enabled: boolean
	conditions: { field: Field; values: string[] }[]
	/** Who gets the lead next, in order, and how many minutes each has to act. */
	rotation_user_ids: string[]
	rotation_minutes: number | null
	/** Only people recorded as speaking the lead's language get it (a lead with no language: as usual). */
	speakers_only: boolean
}
let draft = $state<Draft | null>(null)
let editorEl: HTMLFormElement | undefined = $state()
/** On a narrow screen the editor sits above the list: bring it into view when it opens. */
async function reveal() {
	await tick()
	editorEl?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
	editorEl?.querySelector<HTMLElement>('input, select')?.focus({ preventScroll: true })
}
let busy = $state(false)
/** The rule the delete confirmation window is open for. */
let deleting = $state<{ rule: RoutingRuleResponse; hasLater: boolean } | null>(null)
let dialog: HTMLDialogElement | undefined = $state()
$effect(() => {
	if (deleting && !dialog?.open) dialog?.showModal()
	else if (!deleting && dialog?.open) dialog.close()
})

const teams = $derived(scope.data?.teams ?? [])
const teamName = (id: string) => teams.find((t) => t.id === id)?.name ?? 'Team'
const initials = (name: string) =>
	name
		.split(/\s+/)
		.map((w) => w[0] ?? '')
		.join('')
		.slice(0, 2)
		.toUpperCase()

/** Names made by an earlier version were the whole condition sentence; they are replaced. */
const isOldAutoName = (name: string) => /^(area|looking to|lead source) is /.test(name)

/** A short default name: what the rule checks first, and who gets the leads. */
function autoName(checks: { field: Field; values: string[] }[], person: string): string {
	const first = checks.find((c) => c.values.length)
	const what = first
		? first.field === 'area'
			? first.values.slice(0, 2).join(', ')
			: `${fieldLabel(first.field)} ${first.values.map((v) => valueLabel(first.field, v)).join('/')}`
		: 'Rule'
	return `${what} → ${person || '…'}`.slice(0, 120)
}
const ruleName = (r: RoutingRuleResponse) =>
	isOldAutoName(r.name)
		? autoName(r.conditions, personName(scope.data, r.destination_user_id))
		: r.name

/** Open the editor with a fresh rule draft. */
export function startNew() {
	const team = teams[0]
	draft = {
		id: null,
		revision: 0,
		name: '',
		team_id: team?.id ?? '',
		user_id: '',
		match_mode: 'all',
		enabled: true,
		conditions: [{ field: 'area', values: [] }],
		rotation_user_ids: [],
		rotation_minutes: null,
		speakers_only: false
	}
	void reveal()
}

function edit(r: RoutingRuleResponse) {
	draft = {
		id: r.id,
		revision: r.revision,
		name: isOldAutoName(r.name) ? '' : r.name,
		team_id: r.team_id,
		user_id: r.destination_user_id,
		match_mode: r.match_mode,
		enabled: r.enabled,
		conditions: FIELDS.map((f) => ({
			field: f.id,
			values: r.conditions.filter((c) => c.field === f.id).flatMap((c) => c.values)
		})).filter((c) => c.values.length),
		rotation_user_ids: [...(r.rotation_user_ids ?? [])],
		rotation_minutes: r.rotation_minutes ?? null,
		speakers_only: r.speakers_only ?? false
	}
	void reveal()
}

const filled = (d: Draft) => d.conditions.filter((c) => c.values.length)
/** The chosen agent's name; empty until one is chosen (never "Former member" for no choice). */
const chosenName = (d: Draft) => (d.user_id ? personName(scope.data, d.user_id) : '')
const agents = $derived(teams.find((t) => t.id === draft?.team_id)?.members ?? [])
const unused = (d: Draft, keep?: Field) =>
	FIELDS.filter((f) => f.id === keep || !d.conditions.some((c) => c.field === f.id))

function missing(d: Draft): string[] {
	return [
		!filled(d).length && 'add at least one value to a condition',
		!d.user_id && 'choose the agent who receives the leads',
		d.rotation_user_ids.length > 0 &&
			!(d.rotation_minutes && d.rotation_minutes >= 1 && d.rotation_minutes <= 10080) &&
			'give each person 1 to 10080 minutes to act'
	].filter(Boolean) as string[]
}

/** "JVC + a selected intent + Property Finder → Tulesh Katre". */
function preview(d: Draft): string {
	const parts = filled(d).map((c) =>
		c.values.length === 1
			? valueLabel(c.field, c.values[0])
			: c.field === 'area'
				? c.values.join(' or ')
				: `a selected ${fieldLabel(c.field).toLowerCase()}`
	)
	return `${parts.join(d.match_mode === 'all' ? ' + ' : ' or ')} → ${personName(scope.data, d.user_id)}`
}

const body = (d: Draft): RoutingRuleWrite => ({
	name: (d.name.trim() || autoName(filled(d), chosenName(d))).slice(0, 120),
	team_id: d.team_id,
	destination_user_id: d.user_id,
	match_mode: d.match_mode,
	enabled: d.enabled,
	conditions: filled(d).map((c) => ({ field: c.field, operator: 'is_any_of', values: c.values })),
	rotation_user_ids: d.rotation_user_ids,
	rotation_minutes: d.rotation_user_ids.length ? d.rotation_minutes : null,
	speakers_only: d.speakers_only
})
/** People in the rule (agent first, then the rotation) with no recorded language at all. */
const silent = (d: Draft) =>
	[d.user_id, ...d.rotation_user_ids]
		.map((u) => agents.find((m) => m.user_id === u))
		.filter((m) => m && !(m.languages?.length ?? 0))
		.map((m) => m?.name ?? '')
/** People in the rule's team who could be next in the rotation. */
const nextChoices = (d: Draft) =>
	agents.filter((m) => m.user_id !== d.user_id && !d.rotation_user_ids.includes(m.user_id))

async function save() {
	if (!draft) return
	const d = draft
	busy = true
	const r = await write({
		call: () =>
			d.id === null
				? crm.routing.create(body(d))
				: crm.routing.update(d.id, { ...body(d), expected_revision: d.revision }),
		success: 'Rule saved',
		undoable: false
	})
	busy = false
	if (r) draft = null
}

async function toggle(r: RoutingRuleResponse) {
	busy = true
	await write({
		call: () =>
			crm.routing.update(r.id, {
				name: r.name,
				team_id: r.team_id,
				destination_user_id: r.destination_user_id,
				match_mode: r.match_mode,
				conditions: r.conditions,
				// Sent unchanged: an update replaces the rule, rotation included.
				rotation_user_ids: r.rotation_user_ids ?? [],
				rotation_minutes: r.rotation_minutes ?? null,
				speakers_only: r.speakers_only ?? false,
				enabled: !r.enabled,
				expected_revision: r.revision
			}),
		success: `${ruleName(r)} ${r.enabled ? 'turned off' : 'turned on'}`,
		undoable: false
	})
	busy = false
}

async function move(list: RoutingRuleResponse[], index: number, by: -1 | 1) {
	const order = list.map((r) => r.id)
	;[order[index], order[index + by]] = [order[index + by], order[index]]
	busy = true
	await write({
		call: () =>
			crm.routing.reorder({
				rule_ids: order,
				expected_revisions: Object.fromEntries(list.map((r) => [r.id, r.revision]))
			}),
		success: 'Rule order saved',
		undoable: false
	})
	busy = false
}

async function remove(r: RoutingRuleResponse) {
	busy = true
	const ok = await write({
		call: () => crm.routing.remove(r.id, r.revision),
		success: `Rule “${ruleName(r)}” deleted. New imports no longer use it; leads already assigned keep their agent.`,
		undoable: false
	})
	busy = false
	deleting = null
	if (ok && draft?.id === r.id) draft = null
}

async function turnOffInstead(r: RoutingRuleResponse) {
	deleting = null
	await toggle(r)
}

/** A rule's values on its card: the first few, then "+N" (with the rest on hover). */
const CARD_CHIPS = 3
</script>

<div class="routing">
<div class={['layout', draft && editable && 'editing']}>
	<section class="list" aria-labelledby="rules-h">
		<div class="list-head">
			<div class="list-title"><h2 id="rules-h">Routing rules</h2><span class="rule-count">{rules.data?.length ?? 0} rules</span></div>
			<div class="list-tools">
				<span class="small muted priority">Priority order (top = highest) <Info size={15} /></span>
				{#if editable}<button type="button" class="btn add-rule" disabled={!teams.length} onclick={startNew}><Plus size={18} /> Add rule</button>{/if}
			</div>
		</div>
		<QueryView query={rules} rows={3}>
			{#snippet children(list)}
				{#each list as r, i (r.id)}
					<article class={['rule', !r.enabled && 'off', draft?.id === r.id && 'selected']}>
						<header>
							{#if editable}
								<div class="order">
									<button type="button" class="icon" disabled={busy || i === 0} aria-label="Move {ruleName(r)} up" onclick={() => move(list, i, -1)}><ChevronUp size={16} /></button>
									<button type="button" class="icon" disabled={busy || i === list.length - 1} aria-label="Move {ruleName(r)} down" onclick={() => move(list, i, 1)}><ChevronDown size={16} /></button>
								</div>
							{/if}
							<span class="num">{String(i + 1).padStart(2, '0')}</span>
							<b class="name" title={ruleName(r)}>{ruleName(r)}</b>
							<span class={['status', !r.enabled && 'inactive']}><span></span>{r.enabled ? 'Active' : 'Inactive'}</span>
							{#if editable}
								<label class="switch">
									<input type="checkbox" role="switch" checked={r.enabled} disabled={busy} onchange={() => toggle(r)} aria-label="Use {ruleName(r)}" />
									<span class="track" aria-hidden="true"></span>
									<span class="small">{r.enabled ? 'On' : 'Off'}</span>
								</label>
								<button type="button" class="icon" aria-label="Edit {ruleName(r)}" onclick={() => edit(r)}><Pencil size={16} /></button>
								<button type="button" class="icon danger" aria-label="Delete {ruleName(r)}" title="Delete rule" disabled={busy} onclick={() => (deleting = { rule: r, hasLater: i < list.length - 1 })}><Trash size={16} /></button>
							{:else if !r.enabled}
								<span class="small muted">Off</span>
							{/if}
						</header>
						<div class="rule-flow">
							<div class="body">
								<div class="condition-heading"><b>If a lead matches</b><span class="badge">{r.match_mode === 'all' ? 'Match all' : 'Match any'}</span></div>
								<dl>
									{#each r.conditions as c (c.field)}
										<dt>{#if c.field === 'area'}<MapPin size={17} />{:else if c.field === 'intent'}<Target size={17} />{:else if c.field === 'language'}<Languages size={17} />{:else}<Layers size={17} />{/if}{fieldLabel(c.field)}</dt>
										<dd title={c.values.map((v) => valueLabel(c.field, v)).join(', ')}>
											{#each c.values.slice(0, CARD_CHIPS) as v (v)}<span class="chip">{valueLabel(c.field, v)}</span>{/each}
											{#if c.values.length > CARD_CHIPS}
												<span class="chip">+{c.values.length - CARD_CHIPS}{c.field === 'source' ? ' sources' : ''}</span>
											{/if}
										</dd>
									{/each}
								</dl>
							</div>
							<span class="flow-arrow" aria-hidden="true"><ArrowRight size={20} /></span>
							<footer>
								<b class="assign-label">Assign to</b>
								<div class="destination"><span class="avatar" aria-hidden="true">{initials(personName(scope.data, r.destination_user_id))}</span>
								<div><b>{personName(scope.data, r.destination_user_id)}</b><span class="small muted">Team: {teamName(r.team_id)}</span></div></div>
								{#if r.rotation_user_ids?.length}
									<span class="small muted">
										Then {r.rotation_user_ids.map((u) => personName(scope.data, u)).join(' → ')}, {r.rotation_minutes} min each, then the team pool
									</span>
								{/if}
								{#if r.speakers_only}
									<span class="small muted"><Languages size={14} aria-hidden="true" /> Only to people who speak the lead’s language</span>
								{/if}
							</footer>
						</div>
					</article>
				{:else}
					<div class="empty small muted">
						No rules yet. Example: “Area is JVC → Omar” sends every imported JVC lead to Omar.
					</div>
				{/each}
			{/snippet}
		</QueryView>
		{#if editable}
			<button type="button" class="add-another" disabled={!teams.length} onclick={startNew}>
				<Plus size={16} /> {rules.data?.length ? 'Add another rule' : 'Add a rule'}
			</button>
			{#if scope.data && !teams.length}
				<p class="small muted">Add agents to a team first: a rule sends leads to someone in a team.</p>
			{/if}
		{/if}
		<div class="fallback">
			<span class="fallback-icon" aria-hidden="true"><InboxIcon size={20} /></span>
			<div>
				<b>No matching rule</b>
				<span class="small muted">Lead stays unassigned in the Inbox for a manager to assign.</span>
			</div>
			<a class="btn ghost sm" href="/crm/inbox">Open Inbox <ArrowRight size={14} /></a>
		</div>
		<p class="small muted note"><Info size={14} /> Team membership is checked again before every assignment.</p>
	</section>

	{#if editable && draft}
		{@const d = draft}
		<form
			bind:this={editorEl}
			class="editor"
			aria-labelledby="editor-h"
			onsubmit={(e) => {
				e.preventDefault()
				save()
			}}
		>
			<div class="editor-head">
				<h2 id="editor-h">{d.id === null ? 'New rule' : 'Edit rule'}</h2>
				<button type="button" class="icon" aria-label="Close" onclick={() => (draft = null)}><X size={18} /></button>
			</div>

			<div class="fld">
				<label for="rr-name">Rule name</label>
				<input id="rr-name" maxlength="120" bind:value={d.name} placeholder={filled(d).length || d.user_id ? autoName(filled(d), chosenName(d)) : 'e.g. JVC → Omar (filled in for you)'} />
			</div>

			<h3>Match conditions</h3>
			<Seg
				label="Match conditions"
				items={[
					{ id: 'all', label: 'All conditions' },
					{ id: 'any', label: 'Any condition' }
				]}
				value={d.match_mode}
				onselect={(m) => (d.match_mode = m)}
			/>
			<p class="small muted">All = every condition must match. Any = at least one.</p>
			{#each d.conditions as c, i (c.field)}
				<div class="cond">
					<select aria-label="Condition {i + 1}" bind:value={c.field} onchange={() => (c.values = [])}>
						{#each FIELDS as f (f.id)}
							{@const taken = !unused(d, c.field).some((u) => u.id === f.id)}
							<option value={f.id} disabled={taken}>{f.label}{taken ? ' (in use)' : ''}</option>
						{/each}
					</select>
					<span class="op small">is any of</span>
					<ChipsInput
						label="{fieldLabel(c.field)} values"
						bind:values={c.values}
						options={OPTIONS[c.field]}
						strict={c.field === 'intent'}
						placeholder={PLACEHOLDER[c.field]}
					/>
					<button type="button" class="icon" aria-label="Remove the {fieldLabel(c.field)} condition" disabled={d.conditions.length === 1} onclick={() => d.conditions.splice(i, 1)}><X size={16} /></button>
				</div>
			{/each}
			{#if d.conditions.length < FIELDS.length}
				<div>
					<button type="button" class="btn ghost sm" onclick={() => d.conditions.push({ field: unused(d)[0].id, values: [] })}>
						<Plus size={14} /> Add condition
					</button>
				</div>
			{/if}
			<p class="small muted">Matching uses the lead’s saved values; a lead with no value for a condition doesn’t match it.</p>

			<hr />
			<h3>Assign matching leads to</h3>
			<div class="assign">
				<div class="fld">
					<label for="rr-team">Team</label>
					<select
						id="rr-team"
						bind:value={d.team_id}
						onchange={() => {
							d.user_id = ''
							d.rotation_user_ids = []
						}}
					>
						{#each teams as t (t.id)}<option value={t.id}>{t.name}</option>{/each}
					</select>
				</div>
				<div class="fld">
					<label for="rr-agent">Agent</label>
					<select
						id="rr-agent"
						bind:value={d.user_id}
						onchange={() => (d.rotation_user_ids = d.rotation_user_ids.filter((u) => u !== d.user_id))}
					>
						<option value="">Choose an agent</option>
						{#each agents as m (m.user_id)}<option value={m.user_id}>{m.name}</option>{/each}
					</select>
				</div>
			</div>

			<h3>If they don’t act in time (optional)</h3>
			<p class="small muted">
				Acting means logging contact or changing the lead’s stage. Otherwise the lead moves to the next
				person below, then to the team’s shared pool.
			</p>
			{#if d.rotation_user_ids.length}
				<ol class="rotation">
					{#each d.rotation_user_ids as u, i (u)}
						<li>
							<span>{personName(scope.data, u)}</span>
							<button type="button" class="icon" aria-label="Remove {personName(scope.data, u)} from the rotation" onclick={() => d.rotation_user_ids.splice(i, 1)}><X size={16} /></button>
						</li>
					{/each}
				</ol>
				<div class="fld">
					<label for="rr-minutes">Minutes each person has</label>
					<input id="rr-minutes" type="number" min="1" max="10080" inputmode="numeric" bind:value={d.rotation_minutes} />
				</div>
			{/if}
			{#if d.user_id && nextChoices(d).length}
				<div class="fld">
					<label for="rr-next">{d.rotation_user_ids.length ? 'Then' : 'Next person'}</label>
					<select
						id="rr-next"
						value=""
						onchange={(e) => {
							const u = e.currentTarget.value
							if (u) d.rotation_user_ids.push(u)
							e.currentTarget.value = ''
						}}
					>
						<option value="">Add a person…</option>
						{#each nextChoices(d) as m (m.user_id)}<option value={m.user_id}>{m.name}</option>{/each}
					</select>
				</div>
			{/if}

			<h3>Language</h3>
			<label class="check">
				<input type="checkbox" bind:checked={d.speakers_only} />
				<span>
					Only give the lead to people who speak its language
					<span class="small muted">
						Uses the Language column of the file and the languages recorded for each person below. A lead
						with no language is routed as usual; one nobody in the rule speaks is left for you to assign.
					</span>
				</span>
			</label>
			{#if d.speakers_only && silent(d).length}
				<p class="small muted" role="status">No languages recorded yet for {silent(d).join(', ')}: they would receive no lead with a language under this rule.</p>
			{/if}

			<div class="preview" role="status">
				<b>Rule preview</b>
				<span>{missing(d).length ? `To save: ${missing(d).join(', and ')}.` : preview(d)}</span>
			</div>

			<div class="actions">
				<button type="button" class="btn ghost" onclick={() => (draft = null)}>Cancel</button>
				<button type="submit" class="btn" disabled={busy || missing(d).length > 0}>
					{busy ? 'Saving…' : d.id === null ? 'Save rule' : 'Save changes'}
				</button>
			</div>
		</form>
	{/if}
</div>
</div>

<dialog bind:this={dialog} class="confirm-dialog" aria-labelledby="del-h" onclose={() => (deleting = null)}>
	{#if deleting}
		{@const r = deleting.rule}
		<h2 id="del-h">Delete this rule?</h2>
		<p class="rule-name"><Trash size={16} /> {ruleName(r)}</p>
		<p><b>What changes after you delete it:</b></p>
		<ul>
			<li>
				New imports no longer use this rule. Leads it would have matched
				{deleting.hasLater
					? 'go to the next rule below it that matches, or wait unassigned in the Inbox.'
					: 'wait unassigned in the Inbox for a manager to assign.'}
			</li>
			<li>Leads it already assigned keep their agent. Nothing already in the CRM moves.</li>
			<li>You can’t undo this. To stop using the rule for now, turn it off instead.</li>
		</ul>
		<div class="dialog-actions">
			<button type="button" class="btn ghost" onclick={() => (deleting = null)}>Cancel</button>
			{#if r.enabled}
				<button type="button" class="btn ghost" disabled={busy} onclick={() => turnOffInstead(r)}>Turn off instead</button>
			{/if}
			<button type="button" class="btn danger" disabled={busy} onclick={() => remove(r)}>
				{busy ? 'Deleting…' : 'Delete rule'}
			</button>
		</div>
	{/if}
</dialog>

<style>
	/* Columns follow the space this section really has (the sidebar may be open), not the window. */
	.routing {
		container: routing / inline-size;
	}
	.layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 16px;
		align-items: start;
	}
	/* Stacked: the editor comes first, so it is seen without scrolling past every rule. */
	.layout.editing .editor {
		order: -1;
	}
	@container routing (min-width: 1100px) {
		.layout.editing {
			grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr);
		}
		.layout.editing .editor {
			order: 0;
			position: sticky;
			top: 12px;
		}
	}
	.layout > *,
	.rule {
		min-width: 0;
	}
	h2 {
		margin: 0;
		font-size: 18px;
	}
	h3 {
		margin: 0;
		font-size: 15px;
	}
	.list {
		display: grid;
		grid-template-columns: minmax(0, 1fr);
		gap: 12px;
	}
	.list-head,
	.editor-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}
	.list-head {
		flex-wrap: wrap;
		gap: 12px;
		margin-bottom: 3px;
	}
	.list-title, .list-tools {
		display: flex;
		align-items: center;
		gap: 12px;
	}
	.list-title h2 {
		font-size: 20px;
		font-weight: 700;
	}
	.list-tools {
		flex-wrap: wrap;
	}
	.priority {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}
	.rule-count {
		padding: 3px 9px;
		border-radius: 7px;
		background: var(--routing-tint);
		font-size: 12px;
		white-space: nowrap;
	}
	.add-rule {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		background: var(--routing-blue);
		border-color: var(--routing-blue);
		color: var(--on-accent);
	}
	.icon {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		padding: 0;
		border: 1px solid transparent;
		border-radius: 8px;
		background: none;
		color: var(--text2);
		cursor: pointer;
	}
	.icon:hover:not(:disabled) {
		border-color: var(--sep);
		color: var(--text);
	}
	.icon.danger:hover:not(:disabled) {
		color: var(--red, #e5484d);
	}
	.confirm-dialog {
		width: min(460px, calc(100vw - 32px));
		padding: 20px 22px;
		border: 1px solid var(--sep);
		border-radius: 12px;
		background: var(--card);
		color: var(--text);
	}
	.confirm-dialog::backdrop {
		background: rgb(0 0 0 / 0.55);
	}
	.confirm-dialog h2 {
		margin-bottom: 8px;
	}
	.confirm-dialog p {
		margin: 0 0 8px;
	}
	.confirm-dialog ul {
		margin: 0 0 16px;
		padding-left: 1.2rem;
		display: grid;
		gap: 6px;
		color: var(--text2);
	}
	.rule-name {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 8px 10px;
		border-radius: 8px;
		background: var(--sunk);
		font-weight: 600;
	}
	.dialog-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 8px;
	}
	.icon:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.rule {
		container: rule-card / inline-size;
		display: grid;
		gap: 0;
		overflow: hidden;
		border: 1px solid var(--routing-border);
		border-radius: 12px;
		background: var(--card);
	}
	.rule.selected {
		border-color: var(--routing-blue);
		box-shadow: 0 0 0 1px var(--routing-blue);
	}
	.rule header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 10px;
		padding: 14px 16px;
		background: var(--routing-tint);
	}
	.order {
		display: flex;
		gap: 2px;
	}
	.order .icon {
		width: 24px;
		height: 26px;
		color: var(--text2);
	}
	.num {
		display: grid;
		place-items: center;
		width: 32px;
		height: 34px;
		border-radius: 8px;
		background: color-mix(in srgb, var(--routing-blue) 22%, var(--card));
		font-weight: 700;
	}
	.name {
		min-width: 0;
		overflow-wrap: anywhere;
		font-size: 16px;
		font-weight: 700;
	}
	.status {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 4px 9px;
		border-radius: 7px;
		background: var(--green-bg);
		color: var(--green);
		font-size: 12px;
		font-weight: 600;
	}
	.status > span {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: currentColor;
	}
	.status.inactive {
		background: var(--sunk);
		color: var(--text2);
	}
	.switch {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 7px;
		margin-left: auto;
		cursor: pointer;
	}
	.switch input {
		position: absolute;
		opacity: 0;
		width: 1px;
		height: 1px;
	}
	.track {
		position: relative;
		width: 42px;
		height: 24px;
		border-radius: 14px;
		background: var(--sunk);
		border: 1px solid var(--sep);
		transition: background 0.15s;
	}
	.track::after {
		content: '';
		position: absolute;
		top: 3px;
		left: 3px;
		width: 16px;
		height: 16px;
		border-radius: 50%;
		background: var(--text2);
		transition: transform 0.15s;
	}
	.switch input:checked + .track {
		background: var(--routing-blue);
		border-color: var(--routing-blue);
	}
	.switch input:checked + .track::after {
		transform: translateX(18px);
		background: var(--on-accent);
	}
	.switch input:focus-visible + .track {
		outline: 2px solid var(--routing-blue);
		outline-offset: 3px;
	}
	.rule-flow {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 30px minmax(185px, 0.5fr);
		gap: 16px;
		align-items: center;
		padding: 18px;
	}
	.body {
		min-width: 0;
		display: grid;
		gap: 10px;
	}
	.condition-heading {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 8px;
		font-size: 13px;
	}
	.badge {
		padding: 2px 7px;
		border-radius: 5px;
		background: var(--routing-tint);
		color: var(--text2);
		font-size: 11px;
	}
	dl {
		display: grid;
		grid-template-columns: max-content minmax(0, 1fr);
		align-items: start;
		gap: 10px 16px;
		margin: 0;
		padding: 14px;
		border: 1px solid var(--sep);
		border-radius: 9px;
		background: var(--routing-tint);
	}
	dt {
		display: flex;
		align-items: center;
		gap: 8px;
		padding-top: 3px;
		font-size: 13px;
	}
	dd {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin: 0;
		min-width: 0;
	}
	.chip {
		padding: 3px 9px;
		border: 1px solid var(--routing-border);
		border-radius: 7px;
		background: var(--routing-tint);
		font-size: 12px;
		overflow-wrap: anywhere;
	}
	.flow-arrow {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border-radius: 50%;
		background: var(--sunk);
		color: var(--text2);
	}
	.rule footer {
		display: grid;
		gap: 12px;
		min-width: 0;
		padding: 18px;
		border: 1px solid var(--routing-border);
		border-radius: 10px;
		background: var(--routing-tint);
	}
	.assign-label {
		font-size: 12px;
	}
	.destination {
		display: flex;
		align-items: center;
		gap: 10px;
		min-width: 0;
	}
	.destination > div {
		display: grid;
		gap: 4px;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.avatar {
		display: grid;
		place-items: center;
		flex-shrink: 0;
		width: 38px;
		height: 38px;
		border-radius: 50%;
		background: var(--accent-fill);
		color: var(--on-btn);
		font-size: 13px;
		font-weight: 600;
	}
	.off .rule-flow {
		opacity: 0.7;
	}
	@container rule-card (max-width: 640px) {
		.name {
			flex: 1 1 calc(100% - 110px);
		}
		.rule-flow {
			grid-template-columns: minmax(0, 1fr);
			gap: 12px;
		}
		.flow-arrow {
			display: none;
		}
		.rule footer {
			padding: 12px 14px;
		}
	}
	@container rule-card (max-width: 460px) {
		.rule header {
			gap: 8px;
			padding: 12px;
		}
		.status {
			display: none;
		}
		.rule-flow {
			padding: 12px;
		}
		dl {
			gap: 10px;
			padding: 10px;
		}
	}
	.empty {
		padding: 14px 16px;
		border: 1px solid var(--sep);
		border-radius: 10px;
	}
	.add-another {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 6px;
		padding: 14px;
		border: 1px dashed var(--routing-border);
		border-radius: 10px;
		background: var(--routing-tint);
		color: var(--accent);
		font: inherit;
		font-weight: 600;
		cursor: pointer;
	}
	.add-another:hover:not(:disabled) {
		border-color: var(--accent);
	}
	.add-another:disabled {
		opacity: 0.5;
		cursor: default;
	}
	.fallback {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 14px;
		padding: 16px;
		border: 1px solid color-mix(in srgb, var(--color-warning) 40%, var(--sep));
		border-radius: 10px;
		background: color-mix(in srgb, var(--color-warning) 8%, var(--card));
	}
	.fallback > div {
		flex: 1;
		min-width: 12rem;
		display: grid;
		gap: 2px;
	}
	.fallback-icon {
		display: grid;
		place-items: center;
		width: 40px;
		height: 40px;
		border-radius: 10px;
		background: var(--sunk);
	}
	.fallback a {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		color: var(--accent);
		text-decoration: none;
	}
	.note {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0;
	}
	.editor {
		display: grid;
		gap: 12px;
		padding: 16px 18px;
		border: 1px solid var(--sep);
		border-radius: 10px;
		background: var(--card);
	}
	.editor p {
		margin: 0;
	}
	.cond {
		display: grid;
		grid-template-columns: 9rem max-content minmax(0, 1fr) 30px;
		align-items: center;
		gap: 8px;
	}
	.op {
		padding: 6px 10px;
		border: 1px solid var(--sep);
		border-radius: 8px;
		background: var(--sunk);
	}
	@container routing (max-width: 560px) {
		.cond {
			grid-template-columns: minmax(0, 1fr) 30px;
			grid-template-areas: 'field remove' 'values values';
		}
		.cond select {
			grid-area: field;
		}
		.cond .icon {
			grid-area: remove;
		}
		.cond :global(.wrap) {
			grid-area: values;
		}
		.op {
			display: none;
		}
	}
	hr {
		width: 100%;
		margin: 4px 0;
		border: 0;
		border-top: 1px solid var(--sep);
	}
	.check {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: 10px;
		align-items: start;
	}
	.check input {
		margin-top: 3px;
	}
	.check > span {
		display: grid;
		gap: 4px;
	}
	.rotation {
		display: grid;
		gap: 0.3rem;
		margin: 0;
		padding-left: 1.2rem;
	}
	.rotation li span {
		margin-right: 0.4rem;
	}
	/* The remove button sits on the person's line, not under it. */
	.rotation li .icon {
		display: inline-flex;
		vertical-align: middle;
	}
	.assign {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: 12px;
	}
	.preview {
		display: flex;
		flex-wrap: wrap;
		gap: 8px 24px;
		padding: 12px 14px;
		border: 1px solid var(--sep);
		border-radius: 8px;
		background: var(--sunk);
	}
	.actions {
		display: flex;
		justify-content: flex-end;
		gap: 10px;
	}
</style>
