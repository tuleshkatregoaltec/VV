<script lang="ts">
	import '../app.css';
	const favicon = '/favicon.svg';

	import Navbar from '$lib/components/navigation/Navbar.svelte';
	import FilterBar from '$lib/components/FilterBar.svelte';
	import { page } from '$app/state';

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<div class="h-screen flex flex-col">
	<Navbar />
	{#if page.url.pathname !== '/' && !page.error}
		<FilterBar />
	{/if}
	<div class="flex-1 flex flex-col {page.error ? 'overflow-hidden' : 'overflow-auto'}">
		{@render children()}
	</div>
</div>
