<script lang="ts">
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import PageContainer from '$lib/components/layout/PageContainer.svelte'
import WhatsAppInbox from '$lib/components/whatsapp/WhatsAppInbox.svelte'
import { whatsappScope } from '$lib/queries/whatsapp'
</script>

<svelte:head><title>WhatsApp | Vitevue</title></svelte:head>

<AppFrame>
	<PageContainer>
		{#key whatsappScope()}<WhatsAppInbox />{/key}
	</PageContainer>
</AppFrame>
