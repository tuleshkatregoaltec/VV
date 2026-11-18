<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import { crm } from '../../api'
import type { EmailLead } from '../../api/types'
import { fillTokens, INTENT_LABEL, INTENT_ORDER } from '../../email'
import { crmQueries } from '../../queries'
import { panel } from '../../stores/panel.svelte'
import { write } from '../../write'
import EmailBody from '../ui/EmailBody.svelte'
import EmailButtonInsert from '../ui/EmailButtonInsert.svelte'
import Panel from '../ui/Panel.svelte'

/**
 * Connectors › Email › Templates: write or edit a template the whole company shares.
 * Without an id this is a new template. Types decide which leads Compose suggests it for (none
 * ticked: every type). The preview fills tokens for a sample person.
 */
let { id }: { id?: number } = $props()

const templates = createQuery(() => crmQueries.emailTemplates())
const existing = $derived(id === undefined ? undefined : templates.data?.find((t) => t.id === id))

let name = $state('')
let subject = $state('')
let body = $state('')
let messageEl = $state<HTMLTextAreaElement>()
let types = $state<EmailLead['intent'][]>([])
let loaded = $state(false)
let saving = $state(false)

// Fill the form once the template has loaded; later refetches must not undo typing.
$effect(() => {
	if (loaded || !existing) return
	name = existing.name
	subject = existing.subject
	body = existing.body
	types = [...existing.lead_types]
	loaded = true
})

/** Put a snippet where the cursor is in the message, on its own paragraph. */
function insertAt(snippet: string) {
	const el = messageEl
	const at = el ? el.selectionStart : body.length
	const before = body.slice(0, at).replace(/\s*$/, '')
	const after = body.slice(at).replace(/^\s*/, '')
	body = `${before}${before ? '\n\n' : ''}${snippet}${after ? '\n\n' : ''}${after}`
}

const SAMPLE = { name: 'Sara Khan', email: 'sara.khan@example.com' }

async function submit(e: SubmitEvent) {
	e.preventDefault()
	saving = true
	const input = { name: name.trim(), subject: subject.trim(), body, lead_types: types }
	const r = await write({
		call: () =>
			id === undefined ? crm.email.createTemplate(input) : crm.email.updateTemplate(id, input),
		success: (t) => `Template "${t.name}" saved`
	})
	saving = false
	if (r) panel.close()
}

async function remove() {
	if (
		id === undefined ||
		!confirm(`Delete the template "${name}"? Emails already sent are not affected.`)
	)
		return
	const r = await write({
		call: () => crm.email.removeTemplate(id),
		success: `Template "${name}" deleted`
	})
	if (r !== null) panel.close()
}
</script>

<Panel
	kicker="Email template"
	title={id === undefined ? 'New template' : name || 'Template'}
	sub="Shared with everyone in your company"
>
	<form class="form" onsubmit={submit}>
		<div class="fld">
			<label for="et-name">Template name</label>
			<input id="et-name" required maxlength="120" autocomplete="off" placeholder="New listing alert" bind:value={name} />
		</div>
		<fieldset class="fld et-types">
			<legend>For</legend>
			<div class="et-checks">
				{#each INTENT_ORDER as t (t)}
					<label class="et-check">
						<input
							type="checkbox"
							checked={types.includes(t)}
							onchange={() => (types = types.includes(t) ? types.filter((x) => x !== t) : [...types, t])}
						/>
						{INTENT_LABEL[t]}
					</label>
				{/each}
			</div>
			<span class="small muted">
				{types.length ? 'Compose suggests it for these leads first.' : 'None ticked: suggested for every type.'}
			</span>
		</fieldset>
		<div class="fld">
			<label for="et-subject">Subject</label>
			<input id="et-subject" required maxlength="300" autocomplete="off" bind:value={subject} />
		</div>
		<div class="fld">
			<label for="et-body">Message</label>
			<textarea id="et-body" required rows="12" bind:this={messageEl} bind:value={body}></textarea>
			<EmailButtonInsert oninsert={insertAt} />
			<span class="small muted">
				Personalise with {'{{first_name}}'}, {'{{name}}'} or {'{{email}}'}. A blank line starts a new paragraph.
			</span>
		</div>
		{#if subject || body}
			<div class="fld">
				<span class="lbl">Preview for {SAMPLE.name}</span>
				<div class="et-preview">
					<b>{fillTokens(subject, SAMPLE)}</b>
					<EmailBody text={fillTokens(body, SAMPLE)} />
				</div>
			</div>
		{/if}
		<div class="et-actions">
			<button type="submit" class="btn" disabled={saving}>
				{id === undefined ? 'Save template' : 'Save changes'}
			</button>
			{#if id !== undefined}
				<button type="button" class="btn plain danger-text" onclick={remove}>Delete</button>
			{/if}
		</div>
	</form>
</Panel>

<style>
	.et-preview {
		border: 1px solid var(--line);
		border-radius: 8px;
		background: var(--card-2);
		padding: 10px 12px;
		display: grid;
		gap: 6px;
		font-size: 13px;
	}
	.et-types {
		border: 0;
		padding: 0;
		margin: 0;
		min-width: 0;
	}
	.et-types legend {
		padding: 0;
		margin-bottom: 6px;
		font-size: 12.5px;
		color: var(--text2);
	}
	.et-checks {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}
	.et-check {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 10px;
		border: 1px solid var(--line);
		border-radius: 999px;
		background: var(--card-2);
		font-size: 13px;
		cursor: pointer;
	}
	.et-check input {
		width: auto;
		margin: 0;
	}
	.et-check:has(input:checked) {
		border-color: var(--blue);
	}
	.et-actions {
		display: flex;
		gap: 8px;
	}
</style>
