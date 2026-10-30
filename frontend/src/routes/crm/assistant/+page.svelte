<script lang="ts">
import { createQuery, useQueryClient } from '@tanstack/svelte-query'
import {
	type AssistantConversationResponse,
	assistant,
	assistantKeys
} from '$lib/crm/assistant/api'
import AssistantThread from '$lib/crm/assistant/components/AssistantThread.svelte'
import ConversationList from '$lib/crm/assistant/components/ConversationList.svelte'
import DeleteConversationDialog from '$lib/crm/assistant/components/DeleteConversationDialog.svelte'
import PageHeader from '$lib/crm/components/ui/PageHeader.svelte'

const queryClient = useQueryClient()
const conversationsQuery = createQuery(() => ({
	queryKey: assistantKeys.conversations(),
	queryFn: () => assistant.listConversations()
}))
const conversations = $derived(conversationsQuery.data?.conversations ?? [])

let activeId = $state<number | null>(null)
let collapsed = $state(false)
let deleting = $state<AssistantConversationResponse | null>(null)

const refreshList = () => queryClient.invalidateQueries({ queryKey: assistantKeys.conversations() })

async function ensureConversation(): Promise<number> {
	const created = await assistant.createConversation()
	activeId = created.id
	void refreshList()
	return created.id
}

async function rename(id: number, title: string) {
	await assistant.renameConversation(id, title)
	void refreshList()
}

async function remove() {
	const target = deleting
	deleting = null
	if (!target) return
	await assistant.deleteConversation(target.id)
	if (activeId === target.id) activeId = null
	void refreshList()
}
</script>

<svelte:head><title>Assistant · CRM Beta</title></svelte:head>

<PageHeader title="Assistant" facts="Leads" />

<section class="card assistant">
	<ConversationList
		{conversations}
		{activeId}
		{collapsed}
		onselect={(id) => (activeId = id)}
		onnew={() => (activeId = null)}
		onrename={rename}
		ondelete={(c) => (deleting = c)}
		ontoggle={() => (collapsed = !collapsed)}
	/>
	<AssistantThread conversationId={activeId} {ensureConversation} />
</section>

<DeleteConversationDialog
	open={deleting !== null}
	ondelete={remove}
	oncancel={() => (deleting = null)}
/>

<style>
	.assistant {
		display: flex;
		height: calc(100dvh - 150px);
		min-height: 420px;
	}
</style>
