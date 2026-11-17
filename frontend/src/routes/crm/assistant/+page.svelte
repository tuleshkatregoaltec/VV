<script lang="ts">
import { createInfiniteQuery, useQueryClient } from '@tanstack/svelte-query'
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
const conversationsQuery = createInfiniteQuery(() => ({
	queryKey: assistantKeys.conversations(),
	queryFn: ({ pageParam }) => assistant.listConversations(50, pageParam),
	initialPageParam: 0,
	getNextPageParam: (lastPage, pages) => {
		const loaded = pages.reduce((count, page) => count + page.conversations.length, 0)
		return lastPage.conversations.length && loaded < lastPage.total ? loaded : undefined
	}
}))
const conversations = $derived(
	conversationsQuery.data?.pages.flatMap((page) => page.conversations) ?? []
)

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
		hasMore={conversationsQuery.hasNextPage}
		loadingMore={conversationsQuery.isFetchingNextPage}
		onmore={() => conversationsQuery.fetchNextPage()}
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
