<script lang="ts">
  import { onMount } from 'svelte';
  import { chat, type Conversation } from '$lib/api/chat';
  import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte';

  let {
    selectedId = $bindable(null),
    onSelect = (id: number) => {}
  }: {
    selectedId: number | null;
    onSelect?: (id: number) => void;
  } = $props();

  let conversations = $state<Conversation[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let openMenuId = $state<number | null>(null);
  let renamingId = $state<number | null>(null);
  let renameValue = $state('');
  let deleteConfirmOpen = $state(false);
  let conversationToDelete = $state<number | null>(null);

  onMount(() => {
    loadConversations();

    // Close menu when clicking outside
    const handleClickOutside = () => {
      if (openMenuId !== null) {
        openMenuId = null;
      }
    };
    document.addEventListener('click', handleClickOutside);

    return () => {
      document.removeEventListener('click', handleClickOutside);
    };
  });

  async function loadConversations() {
    loading = true;
    error = null;
    try {
      const result = await chat.getConversations();
      conversations = result.conversations;
      if (!selectedId && conversations.length > 0) {
        selectedId = conversations[0].id;
        onSelect(selectedId);
      }
    } catch (err) {
      console.error('Failed to load conversations:', err);
      error = 'Failed to load conversations';
    } finally {
      loading = false;
    }
  }

  async function createNew() {
    try {
      const newConv = await chat.createConversation({});
      conversations = [newConv, ...conversations];
      selectedId = newConv.id;
      onSelect(newConv.id);
    } catch (err) {
      console.error('Failed to create conversation:', err);
      error = 'Failed to create conversation';
    }
  }

  function startRename(conv: Conversation) {
    renamingId = conv.id;
    renameValue = conv.title || 'New Conversation';
    openMenuId = null;
  }

  async function saveRename(convId: number) {
    if (!renameValue.trim()) {
      renamingId = null;
      return;
    }

    try {
      const updated = await chat.updateConversation(convId, renameValue.trim());
      conversations = conversations.map((c) => (c.id === convId ? updated : c));
      renamingId = null;
    } catch (err) {
      console.error('Failed to rename conversation:', err);
      error = 'Failed to rename conversation';
    }
  }

  function cancelRename() {
    renamingId = null;
    renameValue = '';
  }

  function showDeleteConfirm(convId: number) {
    conversationToDelete = convId;
    deleteConfirmOpen = true;
    openMenuId = null;
  }

  async function confirmDelete() {
    if (conversationToDelete === null) return;

    try {
      await chat.deleteConversation(conversationToDelete);
      conversations = conversations.filter((c) => c.id !== conversationToDelete);

      // If deleted conversation was selected, select the first available one
      if (selectedId === conversationToDelete) {
        if (conversations.length > 0) {
          selectedId = conversations[0].id;
          onSelect(selectedId);
        } else {
          selectedId = null;
        }
      }

      deleteConfirmOpen = false;
      conversationToDelete = null;
    } catch (err) {
      console.error('Failed to delete conversation:', err);
      error = 'Failed to delete conversation';
    }
  }

  function cancelDelete() {
    deleteConfirmOpen = false;
    conversationToDelete = null;
  }

  function toggleMenu(convId: number, event: MouseEvent) {
    event.stopPropagation();
    openMenuId = openMenuId === convId ? null : convId;
  }

  function formatDate(dateString: string): string {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days} days ago`;
    return date.toLocaleDateString();
  }
</script>

<div class="flex flex-col h-full bg-white border-r border-gray-200">
  <div class="p-4 border-b">
    <button
      onclick={createNew}
      class="w-full px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary-dark transition flex items-center justify-center gap-2"
    >
      <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
      </svg>
      New Chat
    </button>
  </div>

  <div class="flex-1 overflow-y-auto">
    {#if loading}
      <div class="p-4 text-center text-gray-500">
        <div class="animate-pulse">Loading...</div>
      </div>
    {:else if error}
      <div class="p-4 text-center">
        <p class="text-red-500 text-sm mb-2">{error}</p>
        <button
          onclick={loadConversations}
          class="text-primary text-sm hover:underline"
        >
          Try again
        </button>
      </div>
    {:else if conversations.length === 0}
      <div class="p-4 text-center text-gray-500">
        <p class="text-sm">No conversations yet</p>
        <p class="text-xs mt-1">Click "New Chat" to start</p>
      </div>
    {:else}
      {#each conversations as conv (conv.id)}
        <div
          class="relative w-full border-b transition {selectedId === conv.id
            ? 'bg-primary-pale border-l-4 border-l-primary'
            : ''}"
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
                class="w-full px-2 py-1 text-sm border border-primary rounded focus:outline-none focus:ring-2 focus:ring-primary"
              />
              <div class="flex gap-2 mt-2">
                <button
                  onclick={() => saveRename(conv.id)}
                  class="px-3 py-1 text-xs bg-primary text-white rounded hover:bg-primary-dark"
                >
                  Save
                </button>
                <button
                  onclick={cancelRename}
                  class="px-3 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300"
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
              class="w-full p-4 pr-12 text-left hover:bg-gray-50 transition"
            >
              <div class="font-medium text-sm truncate">
                {conv.title || 'New Conversation'}
              </div>
              <div class="text-xs text-gray-500 mt-1">
                {formatDate(conv.updated_at)}
              </div>
            </button>

            <!-- Three-dot menu button -->
            <button
              onclick={(e) => toggleMenu(conv.id, e)}
              class="absolute top-4 right-4 p-1 hover:bg-gray-200 rounded transition"
              aria-label="Conversation options"
            >
              <svg class="w-5 h-5 text-gray-600" fill="currentColor" viewBox="0 0 20 20">
                <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
              </svg>
            </button>

            <!-- Dropdown menu -->
            {#if openMenuId === conv.id}
              <div class="absolute right-4 top-12 bg-white border border-gray-200 rounded-lg shadow-lg z-10 min-w-[150px]">
                <button
                  onclick={() => startRename(conv)}
                  class="w-full px-4 py-2 text-left text-sm hover:bg-gray-50 flex items-center gap-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  Rename
                </button>
                <button
                  onclick={() => showDeleteConfirm(conv.id)}
                  class="w-full px-4 py-2 text-left text-sm text-red-600 hover:bg-red-50 flex items-center gap-2"
                >
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                  </svg>
                  Delete
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
