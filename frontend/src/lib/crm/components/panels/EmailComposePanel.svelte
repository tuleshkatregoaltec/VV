<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Plus from 'lucide-svelte/icons/plus'
import X from 'lucide-svelte/icons/x'
import { crm } from '../../api'
import { fillTokens, INTENT_LABEL, suits, typesLabel } from '../../email'
import { plural } from '../../format'
import { crmQueries } from '../../queries'
import { panel } from '../../stores/panel.svelte'
import { toast } from '../../stores/toast.svelte'
import { write } from '../../write'
import EmailBody from '../ui/EmailBody.svelte'
import EmailButtonInsert from '../ui/EmailButtonInsert.svelte'
import Panel from '../ui/Panel.svelte'

/**
 * Write one email and send a personalised copy to each lead through Brevo. Leads come from the
 * page selection or a lead's panel and can be added or removed here; each send lands on the
 * lead's history. Tokens: {{name}}, {{first_name}}, {{email}}; the preview shows the first lead.
 */
let { leadIds }: { leadIds: number[] } = $props()

// svelte-ignore state_referenced_locally
let ids = $state<number[]>([...leadIds])
let find = $state('')
let templateId = $state('')
let subject = $state('')
let body = $state('')
let messageEl = $state<HTMLTextAreaElement>()
let sending = $state(false)

const status = createQuery(() => crmQueries.emailStatus())
const templates = createQuery(() => crmQueries.emailTemplates())
// Who it goes to is looked up by id, so a lead outside the first page still shows.
const picked = createQuery(() => ({ ...crmQueries.emailLeads({ ids }), enabled: ids.length > 0 }))
const found = createQuery(() => crmQueries.emailLeads({ search: find }))

const chosen = $derived(
	ids.length ? (picked.data?.items ?? []).filter((l) => ids.includes(l.id)) : []
)
const sendable = $derived(chosen.filter((l) => !l.do_not_contact))
const first = $derived(sendable[0])
const options = $derived(
	(found.data?.items ?? []).filter((l) => !ids.includes(l.id) && !l.do_not_contact).slice(0, 6)
)
const skipped = $derived(chosen.length - sendable.length)

/** The chosen leads' types; templates that suit them are offered first. */
const intents = $derived([...new Set(sendable.map((l) => l.intent))])
const suggested = $derived((templates.data ?? []).filter((t) => suits(t.lead_types, intents)))
const others = $derived((templates.data ?? []).filter((t) => !suits(t.lead_types, intents)))

/** Why Send is off, in words; empty when it can go. */
const blocked = $derived(
	!sendable.length
		? chosen.length
			? 'Everyone chosen is marked do not contact.'
			: 'Add at least one lead.'
		: status.data && !status.data.configured
			? 'Sending is not available yet.'
			: ''
)

/** Put a snippet where the cursor is in the message, on its own paragraph. */
function insertAt(snippet: string) {
	const el = messageEl
	const at = el ? el.selectionStart : body.length
	const before = body.slice(0, at).replace(/\s*$/, '')
	const after = body.slice(at).replace(/^\s*/, '')
	body = `${before}${before ? '\n\n' : ''}${snippet}${after ? '\n\n' : ''}${after}`
}

const fill = (text: string) => (first ? fillTokens(text, first) : text)

/** Fill subject and message from a template; ask first if something is already written. */
function useTemplate(id: string) {
	const t = templates.data?.find((x) => String(x.id) === id)
	templateId = id
	if (!t) return
	if (
		(subject.trim() || body.trim()) &&
		!confirm(`Replace the subject and message with "${t.name}"?`)
	) {
		templateId = ''
		return
	}
	subject = t.subject
	body = t.body
}

function add(id: number) {
	ids = [...ids, id]
	find = ''
}

async function submit(e: SubmitEvent) {
	e.preventDefault()
	if (blocked) return
	sending = true
	const r = await write({
		call: () => crm.email.send({ enquiry_ids: sendable.map((l) => l.id), subject, body })
	})
	sending = false
	if (!r) return
	if (r.failed) {
		const why = r.results.find((x) => !x.ok)?.error
		toast.show(`${r.sent} sent · ${r.failed} failed${why ? `: ${why}` : ''}`, { tone: 'error' })
	} else toast.show(`${plural(r.sent, 'email')} sent`)
	panel.close()
}
</script>

<Panel
	kicker="Email"
	title="Compose"
	sub={status.data?.sender_email ? `From ${status.data.sender_name ?? ''} <${status.data.sender_email}>` : ''}
>
	<form class="form" onsubmit={submit}>
		<div class="fld">
			<label for="ec-find">To · {plural(sendable.length, 'lead')}</label>
			{#if chosen.length}
				<div class="ec-chips">
					{#each chosen as l (l.id)}
						<span
							class={['ec-chip', l.do_not_contact && 'off']}
							title={l.do_not_contact ? `${l.email} · do not contact, will be skipped` : l.email}
						>
							{l.name} <span class="muted">· {INTENT_LABEL[l.intent]}</span>
							<button
								type="button"
								aria-label="Remove {l.name}"
								onclick={() => (ids = ids.filter((x) => x !== l.id))}
							>
								<X size={12} />
							</button>
						</span>
					{/each}
				</div>
				{#if skipped}
					<span class="small muted">{plural(skipped, 'lead')} marked do not contact will be skipped.</span>
				{/if}
			{/if}
			<input id="ec-find" autocomplete="off" placeholder="Add a lead: name, email, phone" bind:value={find} />
			{#if options.length && (find || !chosen.length)}
				<div class="ec-options">
					{#each options as l (l.id)}
						<button type="button" class="ec-option" onclick={() => add(l.id)}>
							<Plus size={13} />
							<span><b>{l.name}</b> <span class="muted">{INTENT_LABEL[l.intent]} · {l.email}</span></span>
						</button>
					{/each}
				</div>
			{:else if find && found.data && !options.length}
				<span class="small muted">No lead with an email matches.</span>
			{/if}
		</div>
		<div class="fld">
			<label for="ec-template">Template</label>
			<select id="ec-template" value={templateId} onchange={(e) => useTemplate(e.currentTarget.value)}>
				<option value="">No template: write your own</option>
				{#if intents.length}
					<optgroup label="Suggested for {typesLabel(intents)}">
						{#each suggested as t (t.id)}
							<option value={String(t.id)}>{t.name}</option>
						{/each}
					</optgroup>
					{#if others.length}
						<optgroup label="Other templates">
							{#each others as t (t.id)}
								<option value={String(t.id)}>{t.name} · {typesLabel(t.lead_types)}</option>
							{/each}
						</optgroup>
					{/if}
				{:else}
					{#each templates.data ?? [] as t (t.id)}
						<option value={String(t.id)}>{t.name} · {typesLabel(t.lead_types)}</option>
					{/each}
				{/if}
			</select>
			<span class="small muted">
				{#if intents.length && !suggested.length}
					No template is set for {typesLabel(intents)} yet; the others still work.
				{:else}
					Fills in the subject and message; you can still edit them. Manage templates on the Templates tab.
				{/if}
			</span>
		</div>
		<div class="fld">
			<label for="ec-subject">Subject</label>
			<input id="ec-subject" required maxlength="300" autocomplete="off" bind:value={subject} />
		</div>
		<div class="fld">
			<label for="ec-body">Message</label>
			<textarea id="ec-body" required rows="10" bind:this={messageEl} bind:value={body}></textarea>
			<EmailButtonInsert oninsert={insertAt} />
			<span class="small muted">
				Personalise with {'{{first_name}}'}, {'{{name}}'} or {'{{email}}'}. A blank line starts a new paragraph.
			</span>
		</div>
		{#if first && (subject || body)}
			<div class="fld">
				<span class="lbl">Preview for {first.name}</span>
				<div class="ec-preview">
					<b>{fill(subject)}</b>
					<EmailBody text={fill(body)} />
				</div>
			</div>
		{/if}
		{#if blocked && chosen.length}
			<p class="small ec-why">{blocked}</p>
		{/if}
		<div>
			<button type="submit" class="btn" disabled={sending || !!blocked}>
				{sending ? 'Sending…' : `Send to ${plural(sendable.length, 'lead')}`}
			</button>
		</div>
	</form>
</Panel>

<style>
	.ec-chips {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
		margin-bottom: 6px;
	}
	.ec-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 2px 4px 2px 9px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--card-2);
		font-size: 12.5px;
	}
	.ec-chip.off {
		text-decoration: line-through;
		opacity: 0.6;
	}
	.ec-chip button {
		display: inline-grid;
		place-items: center;
		width: 18px;
		height: 18px;
		border: 0;
		border-radius: 50%;
		background: none;
		color: var(--text3);
		cursor: pointer;
	}
	.ec-chip button:hover {
		color: var(--ink);
		background: var(--sep);
	}
	.ec-options {
		display: grid;
		margin-top: 4px;
		border: 1px solid var(--line);
		border-radius: 8px;
		overflow: hidden;
	}
	.ec-option {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: 7px 10px;
		border: 0;
		border-top: 1px solid var(--sep);
		background: var(--card);
		color: var(--ink);
		font-size: 13px;
		text-align: left;
		cursor: pointer;
	}
	.ec-option:first-child {
		border-top: 0;
	}
	.ec-option:hover,
	.ec-option:focus-visible {
		background: var(--card-2);
	}
	.ec-preview {
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--card-2);
		padding: 10px 12px;
		display: grid;
		gap: 6px;
		font-size: 13px;
	}
	.ec-why {
		margin: 0;
		color: var(--amber);
	}
</style>
