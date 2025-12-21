<script lang="ts">
  import { chat, type Message } from '$lib/api/chat';

  let {
    conversationId = $bindable(null)
  }: {
    conversationId: number | null;
  } = $props();

  interface DisplayMessage {
    role: string;
    content: string;
    toolCalls?: string[];
  }

  let inputValue = $state('');
  let messages = $state<DisplayMessage[]>([]);
  let streamController: { close: () => void } | null = $state(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let textareaRef = $state<HTMLTextAreaElement>();
  let messagesEndRef = $state<HTMLDivElement>();

  // Load messages when conversation changes
  $effect(() => {
    if (conversationId) {
      loadMessages();
    } else {
      messages = [];
    }
  });

  // Auto-scroll to bottom when messages change
  $effect(() => {
    if (messages.length > 0 && messagesEndRef) {
      setTimeout(() => {
        messagesEndRef?.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    }
  });

  async function loadMessages() {
    if (!conversationId) return;
    loading = true;
    error = null;
    try {
      const msgs = await chat.getMessages(conversationId);
      messages = msgs.map((m: Message) => ({
        role: m.role,
        content: m.content,
        toolCalls: m.tool_call_ids?.map((id) => `Tool call ${id}`) || []
      }));
    } catch (err) {
      console.error('Failed to load messages:', err);
      error = 'Failed to load messages';
    } finally {
      loading = false;
    }
  }

  function handleSubmit() {
    const text = inputValue.trim();
    if (!text || !conversationId) return;

    if (streamController) streamController.close();

    // Add user message
    messages = [...messages, { role: 'user', content: text }];
    inputValue = '';
    if (textareaRef) textareaRef.style.height = 'auto';

    // Start streaming
    let currentAssistantMessage = '';
    let currentToolCalls: string[] = [];

    streamController = chat.sendMessage(conversationId, text, (rawChunk) => {
      try {
        // Parse SSE data
        const data = JSON.parse(rawChunk);

        if (data.type === 'content') {
          currentAssistantMessage += data.content;
          updateLastMessage('assistant', currentAssistantMessage, currentToolCalls);
        } else if (data.type === 'tool_call_start') {
          currentToolCalls.push(`Calling ${data.tool}...`);
          updateLastMessage('assistant', currentAssistantMessage, currentToolCalls);
        } else if (data.type === 'tool_call_result') {
          const cached = data.cached ? ' (cached)' : '';
          currentToolCalls[currentToolCalls.length - 1] = `✓ ${data.tool}${cached}`;
          updateLastMessage('assistant', currentAssistantMessage, currentToolCalls);
        } else if (data.type === 'done') {
          streamController = null;
        } else if (data.type === 'error') {
          console.error('Stream error:', data.error);
          error = `Error: ${data.error}`;
          streamController = null;
        }
      } catch (e) {
        console.error('Failed to parse chunk:', rawChunk, e);
      }
    });
  }

  function updateLastMessage(role: string, content: string, toolCalls: string[]) {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg?.role === role) {
      messages[messages.length - 1] = { role, content, toolCalls: toolCalls.length > 0 ? [...toolCalls] : undefined };
      messages = [...messages];
    } else {
      messages = [...messages, { role, content, toolCalls: toolCalls.length > 0 ? [...toolCalls] : undefined }];
    }
  }

  function autoResizeTextarea() {
    if (textareaRef) {
      textareaRef.style.height = 'auto';
      const newHeight = Math.min(textareaRef.scrollHeight, 200);
      textareaRef.style.height = newHeight + 'px';
    }
  }

  function stopStreaming() {
    streamController?.close();
    streamController = null;
  }
</script>

<div class="flex flex-col h-full bg-gray-50">
  <!-- Messages -->
  <div class="flex-1 overflow-y-auto p-4 space-y-4">
    {#if loading}
      <div class="text-center text-gray-500">
        <div class="animate-pulse">Loading messages...</div>
      </div>
    {:else if error && messages.length === 0}
      <div class="text-center">
        <p class="text-red-500 text-sm mb-2">{error}</p>
        <button onclick={loadMessages} class="text-primary text-sm hover:underline">
          Try again
        </button>
      </div>
    {:else if messages.length === 0 && conversationId}
      <div class="text-center text-gray-400 mt-8">
        <p class="text-lg mb-2">Welcome to ViteVue AI Assistant!</p>
        <p class="text-sm">Ask me anything about Dubai real estate data</p>
      </div>
    {:else if !conversationId}
      <div class="text-center text-gray-400 mt-8">
        <p class="text-sm">Select or create a conversation to start chatting</p>
      </div>
    {:else}
      {#each messages as msg}
        <div class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}">
          <div
            class="max-w-[80%] rounded-lg p-3 {msg.role === 'user'
              ? 'bg-primary text-white'
              : 'bg-white text-gray-800 shadow-sm border border-gray-200'}"
          >
            <div class="whitespace-pre-wrap">{msg.content}</div>
            {#if msg.toolCalls && msg.toolCalls.length > 0}
              <div
                class="mt-2 pt-2 border-t {msg.role === 'user' ? 'border-primary-dark' : 'border-gray-300'} text-xs space-y-1"
              >
                {#each msg.toolCalls as toolCall}
                  <div class="flex items-center gap-1">
                    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                      <path
                        d="M11 3a1 1 0 100 2h2.586l-6.293 6.293a1 1 0 101.414 1.414L15 6.414V9a1 1 0 102 0V4a1 1 0 00-1-1h-5z"
                      />
                      <path
                        d="M5 5a2 2 0 00-2 2v8a2 2 0 002 2h8a2 2 0 002-2v-3a1 1 0 10-2 0v3H5V7h3a1 1 0 000-2H5z"
                      />
                    </svg>
                    <span>{toolCall}</span>
                  </div>
                {/each}
              </div>
            {/if}
          </div>
        </div>
      {/each}
      <div bind:this={messagesEndRef}></div>
    {/if}
  </div>

  <!-- Input -->
  <div class="border-t p-4 bg-white">
    {#if error && messages.length > 0}
      <div class="mb-2 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-sm">
        {error}
      </div>
    {/if}
    <div class="flex gap-2">
      <textarea
        bind:this={textareaRef}
        bind:value={inputValue}
        oninput={autoResizeTextarea}
        onkeydown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder={conversationId
          ? 'Ask about sales, rentals, developers, projects...'
          : 'Select or create a conversation first'}
        class="flex-1 p-3 border rounded-lg resize-none focus:outline-none focus:ring-2 focus:ring-primary"
        rows="1"
        disabled={!conversationId || streamController !== null}
      ></textarea>
      {#if streamController}
        <button
          onclick={stopStreaming}
          class="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition"
        >
          Stop
        </button>
      {:else}
        <button
          onclick={handleSubmit}
          disabled={!inputValue.trim() || !conversationId}
          class="px-4 py-2 bg-primary text-white rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed hover:bg-primary-dark transition"
        >
          Send
        </button>
      {/if}
    </div>
  </div>
</div>
