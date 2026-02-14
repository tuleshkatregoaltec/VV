<script lang="ts">
  import ConversationSidebar from '$lib/components/dashboard/ConversationSidebar.svelte';
  import ChatBox from '$lib/components/dashboard/ChatBox.svelte';
  import AppShell from '$lib/components/layout/AppShell.svelte';
  import { page } from '$app/stores';
  import { chat } from '$lib/api/chat';
  import { onMount } from 'svelte';

  let selectedConversationId = $state<number | null>(null);
  let initialMessage = $state<string | null>(null);
  let autoSendPending = $state(false);
  let isInitialized = $state(false);

  // Handle navigation state for auto-initialization
  $effect(() => {
    const state = $page.state as {
      conversationId?: number;
      initialMessage?: string;
    };

    if (state?.conversationId && state?.initialMessage) {
      selectedConversationId = state.conversationId;
      initialMessage = state.initialMessage;
      autoSendPending = true;
    }
  });

  // Create a new conversation on mount if none selected
  onMount(async () => {
    // Only create a new conversation if we didn't navigate here with one
    if (!selectedConversationId) {
      try {
        const newConversation = await chat.createConversation({
          title: 'New Conversation'
        });
        selectedConversationId = newConversation.id;
      } catch (error) {
        console.error('Failed to create initial conversation:', error);
      }
    }
    isInitialized = true;
  });
</script>

<svelte:head>
  <title>Chat - Vitevue</title>
</svelte:head>

<AppShell showFilters={false}>
  <div class="flex h-[calc(100vh-64px)] bg-slate-50">
    <div class="w-64 flex-shrink-0 shadow-sm">
      <ConversationSidebar
        bind:selectedId={selectedConversationId}
        onSelect={(id) => (selectedConversationId = id)}
      />
    </div>

    <div class="flex-1 shadow-inner">
      <ChatBox
        bind:conversationId={selectedConversationId}
        initialMessage={initialMessage}
        autoSend={autoSendPending}
        onMessageSent={() => {
          autoSendPending = false;
          initialMessage = null;
        }}
      />
    </div>
  </div>
</AppShell>
