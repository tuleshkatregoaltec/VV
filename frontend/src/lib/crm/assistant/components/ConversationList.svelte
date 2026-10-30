<script lang="ts">
import PanelLeftClose from 'lucide-svelte/icons/panel-left-close'
import PanelLeftOpen from 'lucide-svelte/icons/panel-left-open'
import Pencil from 'lucide-svelte/icons/pencil'
import Plus from 'lucide-svelte/icons/plus'
import Trash2 from 'lucide-svelte/icons/trash-2'
import type { AssistantConversationResponse } from '../api'

let {
	conversations,
	activeId,
	collapsed,
	onselect,
	onnew,
	onrename,
	ondelete,
	ontoggle
}: {
	conversations: AssistantConversationResponse[]
	activeId: number | null
	collapsed: boolean
	onselect: (id: number) => void
	onnew: () => void
	onrename: (id: number, title: string) => void
	ondelete: (conversation: AssistantConversationResponse) => void
	ontoggle: () => void
} = $props()

let editing = $state<number | null>(null)
let draft = $state('')

function startRename(c: AssistantConversationResponse) {
	editing = c.id
	draft = c.title ?? ''
}

function finishRename(id: number) {
	const title = draft.trim()
	editing = null
	if (title) onrename(id, title)
}
</script>

<nav class={['list', collapsed && 'collapsed']} aria-label="Assistant conversations">
	<div class="head">
		<button
			type="button"
			class="btn plain sm"
			aria-label={collapsed ? 'Show conversations' : 'Hide conversations'}
			onclick={ontoggle}
		>
			{#if collapsed}<PanelLeftOpen size={16} />{:else}<PanelLeftClose size={16} />{/if}
		</button>
		{#if !collapsed}
			<button type="button" class="btn ghost sm" onclick={onnew}><Plus size={14} /> New chat</button>
		{/if}
	</div>

	{#if !collapsed}
		<ul>
			{#each conversations as c (c.id)}
				<li class={[c.id === activeId && 'on']}>
					{#if editing === c.id}
						<!-- svelte-ignore a11y_autofocus -->
						<input
							aria-label="Conversation name"
							bind:value={draft}
							autofocus
							onblur={() => finishRename(c.id)}
							onkeydown={(e) => {
								if (e.key === 'Enter') finishRename(c.id)
								if (e.key === 'Escape') editing = null
							}}
						/>
					{:else}
						<button type="button" class="title" onclick={() => onselect(c.id)}>
							{c.title || 'New conversation'}
						</button>
						<button
							type="button"
							class="icon"
							aria-label="Rename conversation"
							onclick={() => startRename(c)}><Pencil size={13} /></button
						>
						<button
							type="button"
							class="icon"
							aria-label="Delete conversation"
							onclick={() => ondelete(c)}><Trash2 size={13} /></button
						>
					{/if}
				</li>
			{:else}
				<li class="none">No conversations yet.</li>
			{/each}
		</ul>
	{/if}
</nav>

<style>
	.list {
		width: 240px;
		flex-shrink: 0;
		border-right: 1px solid var(--sep);
		display: flex;
		flex-direction: column;
		min-height: 0;
	}
	.list.collapsed {
		width: 44px;
	}
	.head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 6px;
		padding: 8px;
		border-bottom: 1px solid var(--sep);
	}
	ul {
		list-style: none;
		margin: 0;
		padding: 6px;
		overflow-y: auto;
	}
	li {
		display: flex;
		align-items: center;
		border-radius: 8px;
	}
	li:hover,
	li.on {
		background: var(--hover);
	}
	li.on .title {
		font-weight: 600;
	}
	li.none {
		color: var(--text2);
		font-size: 13px;
		padding: 8px;
	}
	.title {
		flex: 1;
		min-width: 0;
		text-align: left;
		background: none;
		border: 0;
		color: var(--text);
		padding: 7px 8px;
		font-size: 13.5px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.icon {
		background: none;
		border: 0;
		color: var(--text2);
		padding: 4px;
		opacity: 0;
	}
	li:hover .icon,
	li.on .icon,
	.icon:focus-visible {
		opacity: 1;
	}
	input {
		flex: 1;
		margin: 2px;
	}
	@media (max-width: 720px) {
		.list:not(.collapsed) {
			width: 180px;
		}
	}
</style>
