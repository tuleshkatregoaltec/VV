<script lang="ts">
import { useQueryClient } from '@tanstack/svelte-query'
import BotMessageSquare from 'lucide-svelte/icons/bot-message-square'
import Eraser from 'lucide-svelte/icons/eraser'
import ExternalLink from 'lucide-svelte/icons/external-link'
import Maximize2 from 'lucide-svelte/icons/maximize-2'
import Minimize2 from 'lucide-svelte/icons/minimize-2'
import Plus from 'lucide-svelte/icons/plus'
import X from 'lucide-svelte/icons/x'
import { openLead, panel } from '../../stores/panel.svelte'
import { assistant, assistantKeys } from '../api'
import { widget } from '../widget.svelte'
import AssistantThread from './AssistantThread.svelte'
import DeleteConversationDialog from './DeleteConversationDialog.svelte'

/**
 * The assistant as a small pop-up in the bottom-right corner of every CRM page except the full
 * Assistant page (the layout leaves it out there). Same thread, same confirm cards; its chats are
 * listed on the full page too.
 */
const queryClient = useQueryClient()

async function ensureConversation(): Promise<number> {
	const created = await assistant.createConversation()
	widget.conversationId = created.id
	void queryClient.invalidateQueries({ queryKey: assistantKeys.conversations() })
	return created.id
}

let confirmingClear = $state(false)

// Wide side panels (event forms) take most of the screen, so the chat stays under them.
const WIDE_PANELS = new Set(['new-task', 'edit-event'])
const beside = $derived(Boolean(panel.current) && !WIDE_PANELS.has(panel.current?.kind ?? ''))

/** A lead link in a reply opens the lead's side panel on this page, next to the chat. */
function openLeadLinks(event: MouseEvent) {
	if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey) return
	const link = (event.target as HTMLElement).closest('a')
	const href = link?.getAttribute('href') ?? ''
	const match = /^\/crm\/leads\?lead=(\d+)$/.exec(href)
	if (!match) return
	event.preventDefault()
	openLead(Number(match[1]))
}

/** Clear chat deletes the open conversation and leaves a fresh, empty one. */
async function clearChat() {
	const id = widget.conversationId
	confirmingClear = false
	if (id === null) return
	widget.conversationId = null
	await assistant.deleteConversation(id)
	void queryClient.invalidateQueries({ queryKey: assistantKeys.conversations() })
}
</script>

{#if widget.open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div
		class={['aw-panel', widget.expanded && 'expanded', beside && 'beside']}
		role="dialog"
		aria-label="Assistant"
		tabindex="-1"
		onclick={openLeadLinks}
	>
		<header class="aw-head">
			<span class="aw-title"><BotMessageSquare size={16} /> Assistant</span>
			<button
				type="button"
				class="aw-ico"
				aria-label="New chat"
				title="New chat"
				onclick={() => (widget.conversationId = null)}
			>
				<Plus size={16} />
			</button>
			<button
				type="button"
				class="aw-ico"
				aria-label="Clear chat"
				title="Clear chat"
				disabled={widget.conversationId === null}
				onclick={() => (confirmingClear = true)}
			>
				<Eraser size={15} />
			</button>
			<button
				type="button"
				class="aw-ico"
				aria-label={widget.expanded ? 'Make smaller' : 'Expand'}
				title={widget.expanded ? 'Make smaller' : 'Expand'}
				onclick={() => (widget.expanded = !widget.expanded)}
			>
				{#if widget.expanded}<Minimize2 size={15} />{:else}<Maximize2 size={15} />{/if}
			</button>
			<a
				class="aw-ico"
				href="/crm/assistant"
				aria-label="Open the full Assistant page"
				title="Open the full Assistant page"
				onclick={() => (widget.open = false)}
			>
				<ExternalLink size={15} />
			</a>
			<button
				type="button"
				class="aw-ico"
				aria-label="Close the assistant"
				title="Close"
				onclick={() => (widget.open = false)}
			>
				<X size={16} />
			</button>
		</header>
		<AssistantThread conversationId={widget.conversationId} {ensureConversation} />
	</div>
	<DeleteConversationDialog
		open={confirmingClear}
		title="Clear this chat?"
		confirmText="Clear chat"
		ondelete={clearChat}
		oncancel={() => (confirmingClear = false)}
	/>
{:else}
	<button
		type="button"
		class="aw-launch"
		aria-label="Open the assistant"
		title="Assistant"
		onclick={() => (widget.open = true)}
	>
		<BotMessageSquare size={24} />
	</button>
{/if}

<style>
	.aw-launch {
		position: fixed;
		right: 20px;
		bottom: 20px;
		z-index: 40;
		width: 52px;
		height: 52px;
		border-radius: 50%;
		border: 0;
		display: grid;
		place-items: center;
		background: var(--accent-fill);
		color: var(--on-accent);
		box-shadow: var(--shadow-lg);
		cursor: pointer;
	}
	.aw-launch:hover {
		filter: brightness(1.08);
	}
	.aw-panel {
		position: fixed;
		right: 20px;
		bottom: 20px;
		z-index: 40;
		width: min(400px, calc(100vw - 32px));
		height: min(580px, calc(100dvh - 120px));
		display: flex;
		flex-direction: column;
		background: var(--card);
		color: var(--text);
		border: 1px solid var(--sep);
		border-radius: 14px;
		box-shadow: var(--shadow-lg);
		overflow: hidden;
	}
	.aw-panel.expanded {
		width: min(760px, calc(100vw - 32px));
		height: calc(100dvh - 100px);
	}
	/* With a lead's side panel open, the chat moves to its left and stays usable. */
	@media (min-width: 1100px) {
		.aw-panel.beside {
			right: calc(min(600px, 100%) + 16px);
			z-index: 57;
			width: min(400px, calc(100vw - 600px - 48px));
		}
		.aw-panel.beside.expanded {
			width: min(760px, calc(100vw - 600px - 48px));
		}
	}
	.aw-head {
		display: flex;
		align-items: center;
		gap: 2px;
		padding: 8px 8px 8px 14px;
		border-bottom: 1px solid var(--sep);
	}
	.aw-title {
		flex: 1;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 14px;
		font-weight: 600;
	}
	.aw-ico {
		display: grid;
		place-items: center;
		width: 30px;
		height: 30px;
		border: 0;
		border-radius: 8px;
		background: none;
		color: var(--text2);
		cursor: pointer;
	}
	.aw-ico:disabled {
		opacity: 0.4;
		cursor: default;
	}
	.aw-ico:hover:not(:disabled) {
		background: var(--hover);
		color: var(--text);
	}
	@media (max-width: 600px) {
		.aw-panel,
		.aw-panel.expanded {
			right: 8px;
			bottom: 8px;
			width: calc(100vw - 16px);
			height: calc(100dvh - 80px);
		}
		.aw-launch {
			right: 14px;
			bottom: 14px;
		}
	}
</style>
