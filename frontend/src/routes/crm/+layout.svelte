<script lang="ts">
import { createQuery } from '@tanstack/svelte-query'
import type { Snippet } from 'svelte'
import { afterNavigate } from '$app/navigation'
import { page } from '$app/state'
import '$lib/crm/crm.css'
import AppFrame from '$lib/components/layout/AppFrame.svelte'
import Drawer from '$lib/crm/components/shell/Drawer.svelte'
import Sidebar from '$lib/crm/components/shell/Sidebar.svelte'
import Toast from '$lib/crm/components/shell/Toast.svelte'
import Toolbar from '$lib/crm/components/shell/Toolbar.svelte'
import { crmIdentity } from '$lib/crm/identity.svelte'
import { crmQueries } from '$lib/crm/queries'
import { chrome } from '$lib/crm/stores/chrome.svelte'
import { pendingImports } from '$lib/crm/stores/imports.svelte'
import { panel } from '$lib/crm/stores/panel.svelte'
import { toast } from '$lib/crm/stores/toast.svelte'

let { children }: { children: Snippet } = $props()

const me = createQuery(() => crmQueries.me())
const counts = createQuery(() => crmQueries.counts())
// Only uploads accepted in this session add background reads outside the import pages.
createQuery(() => ({
	...crmQueries.imports(),
	// An accepted upload needs a fresh status read even if pre-upload history is still cached.
	staleTime: 0,
	enabled: Boolean(crmIdentity.key && pendingImports.ids.length)
}))

let identityGeneration = crmIdentity.generation
$effect(() => {
	if (identityGeneration === crmIdentity.generation) return
	identityGeneration = crmIdentity.generation
	panel.closeAll()
	toast.hide()
})

// Deep links: ?lead=3, ?deal=DL-201&tab=documents, ?listing=L1, ?owner=O1
afterNavigate(({ to }) => {
	if (to?.url) panel.syncFromUrl(to.url)
})

/** Home and Inbox fit one screen on a laptop (no page scroll, v2). */
const fit = $derived(/^\/crm(\/inbox)?\/?$/.test(page.url.pathname))
</script>

<svelte:head>
	<title>CRM - Vitevue</title>
</svelte:head>

<AppFrame>
	{#if crmIdentity.key}
	{#key crmIdentity.generation}
	<div class={['crm-root app', panel.current && 'panel-open', chrome.sbHidden && 'nosb', chrome.sbOpen && 'sbopen']}>
		<Sidebar counts={counts.data} me={me.data} />
		<div class="main">
			<Toolbar unread={counts.data?.unread_notifications ?? 0} />
			<!-- AppFrame already renders the page's <main>. -->
			<div class={['content', fit && 'fit']}>
				{@render children()}
			</div>
		</div>
		<Drawer />
		<Toast />
	</div>
	{/key}
	{/if}
</AppFrame>
