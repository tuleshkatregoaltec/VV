<script lang="ts">
  import { chat, type Message } from '$lib/api/chat';
  import { fly, fade } from 'svelte/transition';
  import { cubicOut } from 'svelte/easing';
  import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte';

  let {
    conversationId = $bindable(null),
    initialMessage = null,
    autoSend = false,
    onMessageSent = () => {}
  }: {
    conversationId: number | null;
    initialMessage?: string | null;
    autoSend?: boolean;
    onMessageSent?: () => void;
  } = $props();

  function startConversationWithPrompt(prompt: string) {
    inputValue = prompt;
    handleSubmit();
  }

  interface DisplayMessage {
    role: string;
    content: string;
    toolCalls?: string[];
  }

  let inputValue = $state('');
  let messages = $state<DisplayMessage[]>([]);
  let streamController: { close: () => void } | null = $state(null);
  let isThinking = $state(false);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let textareaRef = $state<HTMLTextAreaElement>();
  let messagesEndRef = $state<HTMLDivElement>();
  let activeStreamConversationId: number | null = $state(null);
  let tokenLimitModalOpen = $state(false);

  // Load messages when conversation changes
  let previousConversationId = $state<number | null>(null);
  
  $effect(() => {
    if (conversationId !== previousConversationId) {
      // Cancel any active stream when switching conversations
      if (streamController && activeStreamConversationId !== conversationId) {
        streamController.close();
        streamController = null;
        activeStreamConversationId = null;
      }

      if (conversationId) {
        loadMessages();
      } else {
        messages = [];
      }
      
      previousConversationId = conversationId;
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

  // Auto-send initial message when navigating from dashboard
  $effect(() => {
    if (autoSend && initialMessage && conversationId && !loading && !streamController) {
      // Set the input value to the initial message
      inputValue = initialMessage;

      // Trigger send after a brief delay for smooth UX
      setTimeout(() => {
        handleSubmit();
        onMessageSent();
      }, 300);
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

    // Store the conversation ID for this stream
    const streamConversationId = conversationId;
    activeStreamConversationId = streamConversationId;

    // Add user message
    messages = [...messages, { role: 'user', content: text }];
    inputValue = '';
    if (textareaRef) textareaRef.style.height = 'auto';

    // Start streaming
    let currentAssistantMessage = '';
    let currentToolCalls: string[] = [];

    streamController = chat.sendMessage(streamConversationId, text, (rawChunk) => {
      // Only update messages if we're still viewing the same conversation
      if (conversationId !== streamConversationId) {
        return;
      }

      try {
        // Parse SSE data
        const data = JSON.parse(rawChunk);

        if (data.type === 'thinking') {
          isThinking = true;
          if (messages[messages.length - 1]?.role !== 'assistant') {
            messages = [...messages, { role: 'assistant', content: '' }];
          }
        } else if (data.type === 'content') {
          isThinking = false;
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
          isThinking = false;
          streamController = null;
          activeStreamConversationId = null;
          setTimeout(() => textareaRef?.focus(), 100);
        } else if (data.type === 'error') {
          console.error('Stream error:', data.error);
          isThinking = false;
          if (data.error === 'token_limit_exceeded') {
            tokenLimitModalOpen = true;
          } else {
            error = `Error: ${data.error}`;
          }
          streamController = null;
          activeStreamConversationId = null;
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
    activeStreamConversationId = null;
    isThinking = false;
  }
</script>

<div class="flex flex-col h-full bg-slate-50">
  <!-- Messages -->
  <div class="flex-1 overflow-y-auto p-6 space-y-6">
    {#if loading}
      <div class="flex items-center justify-center h-full">
        <div class="text-center">
          <div class="inline-block w-12 h-12 border-4 border-slate-200 border-t-primary rounded-full animate-spin mb-4"></div>
          <p class="text-slate-600 font-medium">Loading messages...</p>
        </div>
      </div>
    {:else if error && messages.length === 0}
      <div class="flex items-center justify-center h-full">
        <div class="text-center max-w-md">
          <div class="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mx-auto mb-4">
            <svg class="w-8 h-8 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <p class="text-red-600 text-sm mb-4">{error}</p>
          <button onclick={loadMessages} class="px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-all">
            Try again
          </button>
        </div>
      </div>
    {:else if messages.length === 0 && conversationId}
      {#if autoSend && initialMessage}
        <!-- Don't show empty state if we're about to auto-send -->
        <div class="flex items-center justify-center h-full">
          <div class="text-center">
            <div class="inline-block w-12 h-12 border-4 border-slate-200 border-t-primary rounded-full animate-spin mb-4"></div>
            <p class="text-slate-600 font-medium">Starting conversation...</p>
          </div>
        </div>
      {:else}
        <div class="flex items-center justify-center h-full" in:fade={{ duration: 300, easing: cubicOut }}>
          <div class="text-center max-w-lg">
            <div class="relative w-20 h-20 mx-auto mb-6" in:fly={{ y: -20, duration: 500, delay: 100, easing: cubicOut }}>
              <div class="absolute inset-0 bg-gradient-to-br from-teal-500/20 to-cyan-500/20 rounded-2xl blur-xl"></div>
              <div class="relative w-20 h-20 bg-slate-900 rounded-2xl flex items-center justify-center">
                <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                </svg>
              </div>
            </div>
            <h3 class="text-2xl font-bold text-slate-900 mb-2" in:fly={{ y: 20, duration: 500, delay: 200, easing: cubicOut }}>
              Welcome to ViteVue AI Assistant
            </h3>
            <p class="text-slate-600 mb-6" in:fly={{ y: 20, duration: 500, delay: 300, easing: cubicOut }}>
              Ask me anything about Dubai real estate data, market trends, or property analytics
            </p>
            <div class="grid grid-cols-1 gap-2 text-sm" in:fly={{ y: 20, duration: 500, delay: 400, easing: cubicOut }}>
              <button
                onclick={() => startConversationWithPrompt('What are the average rental prices in Dubai Marina?')}
                class="px-4 py-3 bg-white border border-slate-200 rounded-lg text-left hover:border-slate-300 hover:bg-slate-50 transition-colors"
              >
                <span class="text-slate-400 mr-2">→</span>
                <span class="text-slate-700">"What are the average rental prices in Dubai Marina?"</span>
              </button>
              <button
                onclick={() => startConversationWithPrompt('Show me sales trends for the past 3 months')}
                class="px-4 py-3 bg-white border border-slate-200 rounded-lg text-left hover:border-slate-300 hover:bg-slate-50 transition-colors"
              >
                <span class="text-slate-400 mr-2">→</span>
                <span class="text-slate-700">"Show me sales trends for the past 3 months"</span>
              </button>
              <button
                onclick={() => startConversationWithPrompt('Compare property prices across different areas')}
                class="px-4 py-3 bg-white border border-slate-200 rounded-lg text-left hover:border-slate-300 hover:bg-slate-50 transition-colors"
              >
                <span class="text-slate-400 mr-2">→</span>
                <span class="text-slate-700">"Compare property prices across different areas"</span>
              </button>
            </div>
          </div>
        </div>
      {/if}
    {:else if !conversationId}
      <div class="flex items-center justify-center h-full" in:fade={{ duration: 300, easing: cubicOut }}>
        <div class="text-center max-w-md">
          <div
            class="w-16 h-16 bg-slate-100 rounded-full flex items-center justify-center mx-auto mb-4"
            in:fly={{ y: -20, duration: 500, easing: cubicOut }}
          >
            <svg class="w-8 h-8 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
          </div>
          <p class="text-slate-600 font-medium" in:fly={{ y: 20, duration: 500, delay: 100, easing: cubicOut }}>
            Select or create a conversation to start chatting
          </p>
        </div>
      </div>
    {:else}
      {#each messages as msg, i (i)}
        <div
          class="flex {msg.role === 'user' ? 'justify-end' : 'justify-start'}"
          in:fly={{ y: 10, duration: 250, delay: Math.min(i * 30, 200), easing: cubicOut }}
        >
          <div
            class="max-w-[80%] rounded-2xl p-4 {msg.role === 'user'
              ? 'bg-slate-900 text-white shadow-lg'
              : 'bg-white text-slate-800 shadow-md border border-slate-200 hover:shadow-lg transition-shadow'}"
          >
            {#if isThinking && i === messages.length - 1 && msg.role === 'assistant' && !msg.content}
              <div class="flex items-center gap-2 text-slate-400">
                <div class="flex gap-1 items-center">
                  <div class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style="animation-delay: 0ms"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style="animation-delay: 150ms"></div>
                  <div class="w-1.5 h-1.5 bg-slate-400 rounded-full animate-bounce" style="animation-delay: 300ms"></div>
                </div>
                <span class="text-sm">Thinking...</span>
              </div>
            {:else}
              <div class="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
            {/if}
            {#if msg.toolCalls && msg.toolCalls.length > 0}
              <div
                class="mt-3 pt-3 border-t {msg.role === 'user' ? 'border-slate-700' : 'border-slate-200'} text-xs space-y-2"
              >
                {#each msg.toolCalls as toolCall}
                  <div class="flex items-center gap-2 {msg.role === 'user' ? 'text-slate-300' : 'text-slate-600'}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                    <span class="font-medium">{toolCall}</span>
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

  <!-- Input Area -->
  <div class="border-t border-slate-200 bg-white/80 backdrop-blur-sm p-6">
    {#if error && messages.length > 0}
      <div
        class="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm flex items-center gap-2"
        in:fly={{ y: -10, duration: 300, easing: cubicOut }}
      >
        <svg class="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd" />
        </svg>
        <span>{error}</span>
      </div>
    {/if}

    <!-- Input container with textarea and bottom bar -->
    <div class="border border-slate-300 rounded-xl bg-white overflow-hidden focus-within:ring-2 focus-within:ring-primary/20 focus-within:border-primary transition-all">
      <!-- Textarea -->
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
        class="w-full px-4 pt-3 pb-2 resize-none focus:outline-none bg-white placeholder-slate-400"
        rows="1"
        readonly={!conversationId || streamController !== null}
        style="min-height: 48px; max-height: 200px;"
      ></textarea>

      <!-- Bottom bar with send button -->
      <div class="flex items-center justify-between px-4 py-2">
        <div class="text-xs text-slate-500">
          {#if inputValue.trim() && conversationId && !streamController}
            Press <kbd class="px-1.5 py-0.5 bg-white border border-slate-300 rounded text-slate-700 font-mono text-xs">Enter</kbd> to send
          {:else}
            &nbsp;
          {/if}
        </div>

        <div class="flex items-center gap-2">
          {#if streamController}
            <button
              onclick={stopStreaming}
              class="px-3 py-1.5 bg-red-500 text-white text-sm font-medium rounded-lg hover:bg-red-600 transition-all flex items-center gap-1.5"
              aria-label="Stop streaming"
            >
              <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8 7a1 1 0 00-1 1v4a1 1 0 001 1h4a1 1 0 001-1V8a1 1 0 00-1-1H8z" clip-rule="evenodd" />
              </svg>
              <span>Stop</span>
            </button>
          {:else}
            <button
              onclick={handleSubmit}
              disabled={!inputValue.trim() || !conversationId}
              class="px-3 py-1.5 text-sm font-medium rounded-lg transition-all flex items-center gap-1.5 {inputValue.trim() && conversationId
                ? 'bg-slate-900 text-white hover:bg-slate-800'
                : 'bg-slate-200 text-slate-400 cursor-not-allowed'}"
              aria-label="Send message"
            >
              <span>Send</span>
              <svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
          {/if}
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Token Limit Exceeded Modal -->
<ConfirmModal
  open={tokenLimitModalOpen}
  title="Daily Token Limit Exceeded"
  message="You have reached your daily token usage limit. Please try again tomorrow or contact your organization administrator to increase your limit."
  confirmText="OK"
  confirmVariant="primary"
  onConfirm={() => tokenLimitModalOpen = false}
  onCancel={() => tokenLimitModalOpen = false}
/>
