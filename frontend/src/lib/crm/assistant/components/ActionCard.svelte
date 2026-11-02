<script lang="ts">
import EmailBody from '$lib/crm/components/ui/EmailBody.svelte'
import { fillTokens } from '$lib/crm/email'
import { refreshCrm } from '$lib/crm/write'
import { createActionCard } from '../actionCard.svelte'
import { assistant } from '../api'
import type { ProposedAction } from '../stream'

/**
 * One proposed change: what it does (before → after) and Confirm / Cancel. Share drafts open
 * WhatsApp or email after Confirm; a copied summary needs no confirmation. An email card sends
 * through the Email connector when the agent clicks Send email.
 */
let { action }: { action: ProposedAction } = $props()

const card = createActionCard(action, {
	confirm: assistant.confirmAction,
	cancel: assistant.cancelAction,
	onConfirmed: () => void refreshCrm()
})

const LABELS: Record<string, string> = {
	status: 'Status',
	lost_reason: 'Lost reason',
	next_follow_up: 'Follow-up',
	assignee: 'Assignee',
	note: 'Note',
	to: 'To',
	draft: 'Message',
	shared_with: 'Share with',
	event: 'Event',
	when: 'When',
	subject: 'Subject',
	message: 'Message'
}
const STATE_CHIP: Record<string, { label: string; tone: string }> = {
	confirmed: { label: 'Confirmed', tone: 'green' },
	cancelled: { label: 'Cancelled', tone: 'outline' },
	expired: { label: 'Expired', tone: 'amber' }
}

// Free text (a note, an email) shows exactly as written; codes like follow_up read as words.
const TEXT_KEYS = new Set(['note', 'draft', 'subject', 'message', 'event'])
const show = (value: unknown, key = '') => {
	if (value === null || value === undefined || value === '') return '—'
	return TEXT_KEYS.has(key) ? String(value) : String(value).replaceAll('_', ' ')
}

const rows = $derived(
	Object.keys({ ...(action.before ?? {}), ...(action.after ?? {}) }).map((key) => ({
		label: LABELS[key] ?? key,
		before: action.before && key in action.before ? show(action.before[key], key) : null,
		after: show(action.after?.[key], key)
	}))
)

// An email card shows the email as the lead will get it, like the Email page's compose preview.
const isEmail = action.action_type === 'email_send'
const recipient = String(action.after?.to ?? '')
// {{email}} stays as written: addresses are never shown in the chat.
const fill = (text: unknown) =>
	fillTokens(String(text ?? ''), { name: recipient, email: '{{email}}' })

const isDraft = action.channel === 'whatsapp' || action.channel === 'email'
const confirmText =
	action.action_type === 'email_send'
		? 'Send email'
		: action.channel === 'whatsapp'
			? 'Open WhatsApp draft'
			: action.channel === 'email'
				? 'Open email draft'
				: 'Confirm'

let copied = $state(false)

async function copy() {
	try {
		await navigator.clipboard.writeText(action.text ?? '')
		copied = true
		setTimeout(() => (copied = false), 2000)
	} catch {
		copied = false
	}
}

// The agent can edit an email on its card; Send email then sends their version.
const draftSubject = String(action.after?.subject ?? '')
const draftBody = String(action.after?.message ?? '')
let editing = $state(false)
let subject = $state(draftSubject)
let body = $state(draftBody)
const edited = $derived(subject.trim() !== draftSubject || body.trim() !== draftBody)
const emailReady = $derived(Boolean(subject.trim() && body.trim()))

async function confirm() {
	// Open the tab inside the click so the browser does not block it; fill it when the link arrives.
	const tab = isDraft ? window.open('', '_blank') : null
	if (isEmail && edited) {
		editing = false
		await card.confirm({ subject: subject.trim(), body: body.trim() })
	} else {
		await card.confirm()
	}
	const href = card.result?.href
	if (tab && href) tab.location.href = href
	else tab?.close()
}
</script>

<div class="action card" aria-live="polite">
	<div class="cb">
		<div class="summary">{action.summary}</div>

		{#if action.channel === 'copy'}
			<pre class="share">{action.text}</pre>
			<div class="buttons">
				<button type="button" class="btn ghost sm" onclick={copy}>
					{copied ? 'Copied' : 'Copy'}
				</button>
			</div>
		{:else}
			{#if isEmail}
				<div class="row"><span class="lbl">To:</span> <strong>{recipient}</strong></div>
				{#if editing && card.canAct}
					<label class="lbl" for="em-subject-{action.action_id}">Subject</label>
					<input
						id="em-subject-{action.action_id}"
						class="em-input"
						maxlength="300"
						autocomplete="off"
						bind:value={subject}
					/>
					<label class="lbl" for="em-body-{action.action_id}">Message</label>
					<textarea
						id="em-body-{action.action_id}"
						class="em-input"
						rows="10"
						maxlength="20000"
						bind:value={body}
					></textarea>
					<span class="hint">
						{'{{first_name}}'} and {'{{name}}'} are filled in with the lead’s name. A blank line
						starts a new paragraph.
					</span>
				{:else}
					<div class="lbl">Preview for {recipient}{#if edited}<span class="tag">Edited</span>{/if}</div>
					<div class="email-preview">
						<b>{fill(subject)}</b>
						<EmailBody text={fill(body)} />
					</div>
				{/if}
			{:else if rows.length}
				<dl>
					{#each rows as row (row.label)}
						<div class={['row', row.label === 'Message' && 'long']}>
							<dt>{row.label}:</dt>
							<dd>
								{#if row.before !== null}<span class="before">{row.before}</span> → {/if}<strong
									>{row.after}</strong
								>
							</dd>
						</div>
					{/each}
				</dl>
			{/if}

			{#if card.canAct || card.state === 'working'}
				<div class="buttons">
					<button
						type="button"
						class="btn sm"
						disabled={card.state === 'working' || (isEmail && !emailReady)}
						onclick={confirm}
					>
						{card.state === 'working' ? 'Working…' : confirmText}
					</button>
					{#if isEmail}
						<button
							type="button"
							class="btn ghost sm"
							disabled={card.state === 'working' || (editing && !emailReady)}
							onclick={() => (editing = !editing)}
						>
							{editing ? 'Preview' : 'Edit'}
						</button>
					{/if}
					<button
						type="button"
						class="btn ghost sm"
						disabled={card.state === 'working'}
						onclick={() => card.cancel()}
					>
						Cancel
					</button>
				</div>
				{#if card.error}<p class="err" role="alert">{card.error}</p>{/if}
			{:else if STATE_CHIP[card.state]}
				<div class="buttons">
					<span class="chip {STATE_CHIP[card.state].tone}"
						>{isEmail && card.state === 'confirmed'
							? 'Sent successfully'
							: STATE_CHIP[card.state].label}</span
					>
					{#if card.result?.href}
						<a class="btn ghost sm" href={card.result.href} target="_blank" rel="noopener noreferrer"
							>Open draft again</a
						>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>

<style>
	.action {
		margin-top: 8px;
		max-width: 520px;
	}
	.summary {
		font-weight: 600;
		margin-bottom: 6px;
	}
	dl {
		margin: 0 0 8px;
		display: grid;
		gap: 3px;
		font-size: 13.5px;
	}
	.row {
		display: flex;
		gap: 6px;
	}
	dt {
		color: var(--text2);
	}
	dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.lbl {
		color: var(--text2);
		font-size: 13px;
	}
	.em-input {
		width: 100%;
		margin: 2px 0 6px;
		font: inherit;
		font-size: 13.5px;
	}
	textarea.em-input {
		resize: vertical;
		min-height: 160px;
	}
	.hint {
		display: block;
		color: var(--text2);
		font-size: 12px;
		margin-bottom: 8px;
	}
	.tag {
		margin-left: 6px;
		font-size: 11.5px;
		padding: 1px 6px;
		border-radius: 999px;
		background: var(--sunk);
		color: var(--text2);
	}
	.email-preview {
		border: 1px solid var(--sep);
		border-radius: 8px;
		background: var(--card-2);
		padding: 10px 12px;
		display: grid;
		gap: 6px;
		font-size: 13.5px;
		max-height: 320px;
		overflow-y: auto;
		margin: 4px 0 2px;
	}
	/* A message keeps its paragraphs and sits under its label. */
	.row.long {
		flex-direction: column;
		gap: 2px;
	}
	.row.long dd {
		white-space: pre-wrap;
		max-height: 220px;
		overflow-y: auto;
	}
	.before {
		color: var(--text2);
	}
	.buttons {
		display: flex;
		gap: 6px;
		align-items: center;
		flex-wrap: wrap;
	}
	.share {
		white-space: pre-wrap;
		font: inherit;
		font-size: 13.5px;
		background: var(--sunk);
		border-radius: 8px;
		padding: 8px 10px;
		margin: 0 0 8px;
	}
	.err {
		color: var(--red);
		font-size: 13px;
		margin: 6px 0 0;
	}
</style>
