<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';

	export const prerender = false;

	onMount(() => {
		goto('/admin/organizations');
	});
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
	<p class="text-gray-600">Redirecting to admin panel...</p>
</div>
