<script lang="ts">
import '../app.css'
import { QueryClientProvider } from '@tanstack/svelte-query'
import type { Snippet } from 'svelte'
import type { LayoutData } from './$types'

let { children, data }: { children: Snippet; data: LayoutData } = $props()
</script>

<svelte:head>
	<link rel="icon" href="/icon.svg" />
	<meta name="author" content="Vitevue" />
	<meta name="theme-color" content="#0B1B2B" />
	<meta property="og:type" content="website" />
	<meta property="og:site_name" content="Vitevue" />
	<meta name="twitter:card" content="summary_large_image" />
</svelte:head>

<QueryClientProvider client={data.queryClient}>
	{@render children()}
</QueryClientProvider>
