<script lang="ts">
import { createConversationSelection } from '$lib/chat/conversationSelection.svelte'
import ChatBox from '$lib/components/dashboard/ChatBox.svelte'
import ConversationSidebar from '$lib/components/dashboard/ConversationSidebar.svelte'
import { crmPresentationMode } from '$lib/crm/api'
import PresentationConversation from '$lib/crm/components/PresentationConversation.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'

const selection = createConversationSelection()
</script>

<svelte:head><title>Assistant · CRM Beta</title></svelte:head>

<PageHeader title="Assistant">
	{#snippet note()}
		<span class="chip outline">Same lead access as your CRM · Confirm changes</span>
	{/snippet}
</PageHeader>

{#if crmPresentationMode}
<PresentationConversation />
{:else}
<section class="grid min-h-[600px] grid-cols-1 gap-3 md:h-[72vh] md:grid-cols-[240px_1fr]" aria-label="Your CRM assistant">
	<aside class="max-h-56 overflow-hidden rounded-lg border border-border md:max-h-none" aria-label="Conversation history">
		<ConversationSidebar assistant="crm" bind:selectedId={selection.id} onSelect={(id) => (selection.id = id)} />
	</aside>
	<div class="min-h-[450px] overflow-hidden rounded-lg border border-border md:min-h-0">
		<ChatBox assistant="crm" bind:conversationId={selection.id} voice />
	</div>
</section>

{/if}
