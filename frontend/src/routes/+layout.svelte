<script lang="ts">
	import '../app.css';
	const favicon = '/favicon.svg';

	import { QueryClientProvider } from '@tanstack/svelte-query';
  	import type { LayoutData } from './$types';
	import type { Snippet } from 'svelte';
	import { onMount } from 'svelte';

	import Navbar from '$lib/components/navigation/Navbar.svelte';
	import FilterBar from '$lib/components/filters/FilterBar.svelte'
	import { page } from '$app/state';
    import { authStore } from '$lib/stores/auth.svelte';


	let { children, data } : {children: Snippet, data: LayoutData} = $props();

	onMount(() => {
		authStore.checkSession();
	});

</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>


{#if authStore.loading}
  <div>Loading...</div>
{:else if !authStore.authenticated}
  <div>
    <h1>Please log in</h1>
    <button onclick={() => authStore.login()}>Login</button>
  </div>
{:else}
  <div>
  </div>
{/if}
    <p>Welcome, {authStore.user?.email}</p>
    <button onclick={() => authStore.logout()}>Logout</button>
<QueryClientProvider client={data.queryClient}>
<div class="h-screen flex flex-col">
	{#if page.url.pathname !=='/'}
	<Navbar />
	{/if}
	{#if page.url.pathname !== '/' && !page.error}
		<FilterBar />
	{/if}
	<div class="flex-1 flex flex-col {page.error ? 'overflow-hidden' : 'overflow-auto'}">
		{@render children()}
	</div>
</div>
</QueryClientProvider>