<script lang="ts">
import { refreshCrm } from '$lib/crm/write'
import { createActionCard } from '../actionCard.svelte'
import { assistant } from '../api'
import type { ProposedAction } from '../stream'

/**
 * One proposed change: what it does (before → after) and Confirm / Cancel. Share drafts open
 * WhatsApp or email after Confirm; a copied summary needs no confirmation.
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
	when: 'When'
}
const STATE_CHIP: Record<string, { label: string; tone: string }> = {
	confirmed: { label: 'Confirmed', tone: 'green' },
	cancelled: { label: 'Cancelled', tone: 'outline' },
	expired: { label: 'Expired', tone: 'amber' }
}

const show = (value: unknown) =>
	value === null || value === undefined || value === '' ? '—' : String(value).replaceAll('_', ' ')

const rows = $derived(
	Object.keys({ ...(action.before ?? {}), ...(action.after ?? {}) }).map((key) => ({
		label: LABELS[key] ?? key,
		before: action.before && key in action.before ? show(action.before[key]) : null,
		after: show(action.after?.[key])
	}))
)

const isDraft = action.channel === 'whatsapp' || action.channel === 'email'
const confirmText =
	action.channel === 'whatsapp'
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

async function confirm() {
	// Open the tab inside the click so the browser does not block it; fill it when the link arrives.
	const tab = isDraft ? window.open('', '_blank') : null
	await card.confirm()
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
			{#if rows.length}
				<dl>
					{#each rows as row (row.label)}
						<div class="row">
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
						disabled={card.state === 'working'}
						onclick={confirm}
					>
						{card.state === 'working' ? 'Working…' : confirmText}
					</button>
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
					<span class="chip {STATE_CHIP[card.state].tone}">{STATE_CHIP[card.state].label}</span>
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
