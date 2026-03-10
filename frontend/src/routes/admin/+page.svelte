<script lang="ts">
import { onMount } from 'svelte'
import { goto } from '$app/navigation'

onMount(() => {
	goto('/admin/organizations')
})
</script>

<div class="min-h-screen bg-slate-50">
	<div class="max-w-7xl mx-auto px-4 py-8">
		<p class="text-slate-600">Redirecting to admin panel...</p>
	</div>
</div>
