<script lang="ts">
  import ConversationSidebar from '$lib/components/dashboard/ConversationSidebar.svelte';
  import ChatBox from '$lib/components/dashboard/ChatBox.svelte';

  let selectedConversationId = $state<number | null>(null);
</script>

<svelte:head>
  <title>Chat - ViteVue</title>
</svelte:head>

<div class="flex h-screen">
  <div class="w-64 flex-shrink-0">
    <ConversationSidebar
      bind:selectedId={selectedConversationId}
      onSelect={(id) => (selectedConversationId = id)}
    />
  </div>

  <div class="flex-1">
    <ChatBox bind:conversationId={selectedConversationId} />
  </div>
</div>
