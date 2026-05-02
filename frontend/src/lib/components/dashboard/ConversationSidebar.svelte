<script lang="ts">
import { onMount } from 'svelte'
import { type ConversationResponse, chat } from '$lib/api/chat'
import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte'

let {
	selectedId = $bindable(null),
	onSelect = (_id: number) => {}
}: {
	selectedId: number | null
	onSelect?: (id: number) => void
} = $props()

let conversations = $state<ConversationResponse[]>([])
let loading = $state(true)
let error = $state<string | null>(null)
let openMenuId = $state<number | null>(null)
let renamingId = $state<number | null>(null)
let renameValue = $state('')
let deleteConfirmOpen = $state(false)
let conversationToDelete = $state<number | null>(null)

onMount(() => {
	loadConversations()

	// Close menu when clicking outside
	const handleClickOutside = () => {
		if (openMenuId !== null) {
			openMenuId = null
		}
	}
	document.addEventListener('click', handleClickOutside)

	return () => {
		document.removeEventListener('click', handleClickOutside)
	}
})

async function loadConversations() {
	loading = true
	error = null
	try {
		const result = await chat.getConversations()
		conversations = result.conversations
		if (!selectedId && conversations.length > 0) {
			selectedId = conversations[0].id
			onSelect(selectedId)
		}
	} catch (err) {
		console.error('Failed to load conversations:', err)
		error = 'Failed to load conversations'
	} finally {
		loading = false
	}
}

async function createNew() {
	try {
		const newConv = await chat.createConversation({})
		conversations = [newConv, ...conversations]
		selectedId = newConv.id
		onSelect(newConv.id)
	} catch (err) {
		console.error('Failed to create conversation:', err)
		error = 'Failed to create conversation'
	}
}

function startRename(conv: ConversationResponse) {
	renamingId = conv.id
	renameValue = conv.title || 'New Conversation'
	openMenuId = null
}

async function saveRename(convId: number) {
	if (!renameValue.trim()) {
		renamingId = null
		return
	}

	try {
		const updated = await chat.updateConversation(convId, renameValue.trim())
		conversations = conversations.map((c) => (c.id === convId ? updated : c))
		renamingId = null
	} catch (err) {
		console.error('Failed to rename conversation:', err)
		error = 'Failed to rename conversation'
	}
}

function cancelRename() {
	renamingId = null
	renameValue = ''
}

function showDeleteConfirm(convId: number) {
	conversationToDelete = convId
	deleteConfirmOpen = true
	openMenuId = null
}

async function confirmDelete() {
	if (conversationToDelete === null) return

	try {
		await chat.deleteConversation(conversationToDelete)
		conversations = conversations.filter((c) => c.id !== conversationToDelete)

		// If deleted conversation was selected, select the first available one
		if (selectedId === conversationToDelete) {
			if (conversations.length > 0) {
				selectedId = conversations[0].id
				onSelect(selectedId)
			} else {
				selectedId = null
			}
		}

		deleteConfirmOpen = false
		conversationToDelete = null
	} catch (err) {
		console.error('Failed to delete conversation:', err)
		error = 'Failed to delete conversation'
	}
}

function cancelDelete() {
	deleteConfirmOpen = false
	conversationToDelete = null
}

function toggleMenu(convId: number, event: MouseEvent) {
	event.stopPropagation()
	openMenuId = openMenuId === convId ? null : convId
}

function formatDate(dateString: string): string {
	const date = new Date(dateString)
	const now = new Date()
	const diff = now.getTime() - date.getTime()
	const days = Math.floor(diff / (1000 * 60 * 60 * 24))

	if (days === 0) return 'Today'
	if (days === 1) return 'Yesterday'
	if (days < 7) return `${days} days ago`
	return date.toLocaleDateString()
}
</script>

<div class="flex flex-col h-full bg-white border-r border-slate-200">
	<div class="p-4 border-b border-slate-200">
		<button
			onclick={createNew}
			class="group w-full px-4 py-3 bg-slate-900 text-white font-medium rounded-xl hover:bg-slate-800 transition-all shadow-md hover:shadow-lg flex items-center justify-center gap-2"
		>
			<svg
				class="w-5 h-5 group-hover:rotate-90 transition-transform duration-300"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				viewBox="0 0 24 24"
			>
				<path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
			</svg>
			New Chat
		</button>
	</div>

	<div class="flex-1 overflow-y-auto">
		{#if loading}
			<div class="p-6 text-center">
				<div
					class="inline-block w-8 h-8 border-3 border-slate-200 border-t-slate-900 rounded-full animate-spin mb-3"
				></div>
				<p class="text-slate-600 text-sm font-medium">Loading...</p>
			</div>
		{:else if error}
			<div class="p-6 text-center">
				<div class="w-12 h-12 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-3">
					<svg class="w-6 h-6 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
						/>
					</svg>
				</div>
				<p class="text-red-600 text-sm mb-3">{error}</p>
				<button
					onclick={loadConversations}
					class="px-3 py-2 bg-red-500 text-white text-sm rounded-lg hover:bg-red-600 transition-all"
				>
					Try again
				</button>
			</div>
		{:else if conversations.length === 0}
			<div class="p-6 text-center">
				<div
					class="w-16 h-16 bg-slate-100 rounded-lg flex items-center justify-center mx-auto mb-4"
				>
					<svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							stroke-width="2"
							d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
						/>
					</svg>
				</div>
				<p class="text-slate-700 font-medium text-sm mb-1">No conversations yet</p>
				<p class="text-slate-500 text-xs">Click "New Chat" to start</p>
			</div>
		{:else}
			{#each conversations as conv (conv.id)}
				<div
					class="relative w-full border-b border-slate-100 transition-all {selectedId === conv.id
						? 'bg-slate-100 border-l-4 border-l-slate-900'
						: 'hover:bg-slate-50'}"
				>
					{#if renamingId === conv.id}
						<div class="p-4">
							<input
								type="text"
								bind:value={renameValue}
								onkeydown={(e) => {
									if (e.key === 'Enter') saveRename(conv.id);
									if (e.key === 'Escape') cancelRename();
								}}
								class="w-full px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-slate-900/20 focus:border-slate-900 transition-all"
							/>
							<div class="flex gap-2 mt-3">
								<button
									onclick={() => saveRename(conv.id)}
									class="flex-1 px-3 py-2 text-xs font-medium bg-slate-900 text-white rounded-lg hover:bg-slate-800 transition-all"
								>
									Save
								</button>
								<button
									onclick={cancelRename}
									class="flex-1 px-3 py-2 text-xs font-medium bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 transition-all"
								>
									Cancel
								</button>
							</div>
						</div>
					{:else}
						<button
							onclick={() => {
								selectedId = conv.id;
								onSelect(conv.id);
							}}
							class="w-full p-4 pr-12 text-left transition-all group"
						>
							<div class="font-semibold text-sm truncate text-slate-900 group-hover:text-slate-700">
								{conv.title || 'New Conversation'}
							</div>
							<div class="text-xs text-slate-500 mt-1 flex items-center gap-1.5">
								<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
									/>
								</svg>
								{formatDate(conv.updated_at)}
							</div>
						</button>

						<!-- Three-dot menu button -->
						<button
							onclick={(e) => toggleMenu(conv.id, e)}
							class="absolute top-4 right-4 p-1.5 hover:bg-slate-200 rounded-lg transition-all {selectedId ===
							conv.id
								? 'opacity-100'
								: 'opacity-0 group-hover:opacity-100'}"
							aria-label="Conversation options"
						>
							<svg class="w-4 h-4 text-slate-600" fill="currentColor" viewBox="0 0 20 20">
								<path
									d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z"
								/>
							</svg>
						</button>

						<!-- Dropdown menu -->
						{#if openMenuId === conv.id}
							<div
								class="absolute right-4 top-12 bg-white border border-slate-200 rounded-xl shadow-xl z-10 min-w-[160px] overflow-hidden"
							>
								<button
									onclick={() => startRename(conv)}
									class="w-full px-4 py-2.5 text-left text-sm hover:bg-slate-50 flex items-center gap-2 transition-colors text-slate-700"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
										/>
									</svg>
									<span class="font-medium">Rename</span>
								</button>
								<div class="h-px bg-slate-100"></div>
								<button
									onclick={() => showDeleteConfirm(conv.id)}
									class="w-full px-4 py-2.5 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2 transition-colors"
								>
									<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
										/>
									</svg>
									<span class="font-medium">Delete</span>
								</button>
							</div>
						{/if}
					{/if}
				</div>
			{/each}
		{/if}
	</div>
</div>

<ConfirmModal
	open={deleteConfirmOpen}
	title="Delete Conversation"
	message="Are you sure you want to delete this conversation? This action cannot be undone."
	confirmText="Delete"
	cancelText="Cancel"
	confirmVariant="danger"
	onConfirm={confirmDelete}
	onCancel={cancelDelete}
/>
