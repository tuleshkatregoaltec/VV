<script lang="ts">
  import { onMount } from 'svelte';
  import { chat, type Conversation } from '$lib/api/chat';

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

  onMount(async () => {
    await loadConversations();
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
        <button
          onclick={() => {
            selectedId = conv.id;
            onSelect(conv.id);
          }}
          class="w-full p-4 text-left hover:bg-gray-50 border-b transition {selectedId === conv.id
            ? 'bg-primary-pale border-l-4 border-l-primary'
            : ''}"
        >
          <div class="font-medium text-sm truncate">
            {conv.title || 'New Conversation'}
          </div>
          <div class="text-xs text-gray-500 mt-1">
            {formatDate(conv.updated_at)}
          </div>
        </button>
      {/each}
    {/if}
  </div>
</div>
