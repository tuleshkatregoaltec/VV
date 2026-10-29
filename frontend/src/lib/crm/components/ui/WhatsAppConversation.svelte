<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import Send from 'lucide-svelte/icons/send'
import type { WhatsAppThread } from '../../api/types'
import { stamp } from '../../email'
import { crmQueries } from '../../queries'
import { fillPreview, MESSAGE_STATUS, messageTitle, windowHoursLeft } from '../../whatsapp'
import { write } from '../../write'
import Chip from './Chip.svelte'

/**
 * One WhatsApp chat between the agent and a lead, oldest first, and what can be sent next. Agents
 * see plain words: WhatsApp's approved templates are "opening messages", needed to start a chat or
 * write again more than 24 hours after the lead's last message; inside those 24 hours any reply
 * goes. Used on Lead › Conversation and on Connectors › WhatsApp › a chat.
 */
let {
	thread,
	name,
	configured,
	sendTemplate,
	reply
}: {
	thread: WhatsAppThread
	/** The lead's name; null when the number is not on a lead yet. */
	name: string | null
	configured: boolean
	sendTemplate: (t: { name: string; language: string }) => Promise<unknown>
	reply: (body: string) => Promise<unknown>
} = $props()

const uid = $props.id()
const templates = createQuery(() => crmQueries.whatsappTemplates())
const approved = $derived((templates.data ?? []).filter((t) => t.review === 'approved'))
let templateKey = $state('')
const template = $derived(approved.find((t) => `${t.name}:${t.language}` === templateKey))
let body = $state('')
let sending = $state(false)
const hours = $derived(windowHoursLeft(thread.window_ends_at))
const them = $derived(name ?? 'Contact')
const firstName = $derived(name?.split(/\s+/)[0] ?? null)

async function submitTemplate(e: SubmitEvent) {
	e.preventDefault()
	if (!template) return
	sending = true
	const r = await write({
		call: () => sendTemplate({ name: template.name, language: template.language }),
		success: 'Message sent on WhatsApp'
	})
	sending = false
	if (r) templateKey = ''
}

async function submitReply(e: SubmitEvent) {
	e.preventDefault()
	if (!body.trim()) return
	sending = true
	const r = await write({ call: () => reply(body.trim()), success: 'Sent on WhatsApp' })
	sending = false
	if (r) body = ''
}
</script>

{#if thread.messages.length}
	<div class="thread" aria-label="WhatsApp conversation">
		{#each thread.messages as m (m.id)}
			<div class={['msg', m.direction === 'out' && 'me']}>
				<div class="w">
					{m.direction === 'out' ? 'You' : them} · {stamp(m.at)}
					{#if m.status}
						<Chip tone={MESSAGE_STATUS[m.status].tone}>{MESSAGE_STATUS[m.status].label}</Chip>
					{/if}
				</div>
				<div class="wa-body">{m.body}</div>
				{#if m.error}<div class="small wa-err">{m.error}</div>{/if}
			</div>
		{/each}
	</div>
{/if}

{#if !configured}
	<div class="notice">
		WhatsApp is not connected yet. Ask your administrator to connect the business number to message from here.
	</div>
{:else if !thread.wa_number}
	<div class="notice">No WhatsApp number on file. Add a mobile number to message them.</div>
{:else if thread.opted_out}
	<div class="notice">This contact opted out of WhatsApp messages. Vitevue will not send to them.</div>
{:else if hours > 0}
	<form class="form wa-compose" onsubmit={submitReply}>
		<label class="sr-only" for="{uid}-reply">Reply on WhatsApp</label>
		<textarea id="{uid}-reply" rows="2" placeholder="Type a reply…" bind:value={body}></textarea>
		<div class="form-actions">
			<span class="small muted">You can reply for {hours} more {hours === 1 ? 'hour' : 'hours'}</span>
			<span class="wa-grow"></span>
			<button type="submit" class="btn sm" disabled={sending || !body.trim()}>
				<Send size={14} />
				{sending ? 'Sending…' : 'Send'}
			</button>
		</div>
	</form>
{:else}
	<form class="form wa-compose" onsubmit={submitTemplate}>
		<div class="fld">
			<label for="{uid}-tpl">
				{thread.messages.length
					? `${them} hasn’t written in over 24 hours. WhatsApp needs an opening message to continue.`
					: `Start the chat with an opening message`}
			</label>
			<select id="{uid}-tpl" bind:value={templateKey} disabled={!approved.length}>
				<option value="">{approved.length ? 'Choose a message' : 'No opening messages yet — ask your administrator'}</option>
				{#each approved as tp (`${tp.name}:${tp.language}`)}
					<option value="{tp.name}:{tp.language}">{messageTitle(tp.name)}{approved.some((o) => o.name === tp.name && o.language !== tp.language) ? ` · ${tp.language}` : ''}</option>
				{/each}
			</select>
		</div>
		{#if template}
			<div class="msg me wa-preview">
				<div class="w">Preview</div>
				<div class="wa-body">{fillPreview(template.body, firstName)}</div>
			</div>
		{/if}
		<div class="form-actions">
			<span class="wa-grow"></span>
			<button type="submit" class="btn sm" disabled={sending || !template}>
				<Send size={14} />
				{sending ? 'Sending…' : 'Send'}
			</button>
		</div>
	</form>
{/if}

<style>
	.wa-body {
		white-space: pre-wrap;
		margin-top: 4px;
	}
	.wa-err {
		color: var(--red);
		margin-top: 4px;
	}
	.wa-compose {
		margin-top: 0.6rem;
	}
	.wa-preview {
		justify-self: end;
	}
	.wa-grow {
		flex: 1;
	}
</style>
