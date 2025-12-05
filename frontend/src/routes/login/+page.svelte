<script lang="ts">
    import { onMount } from 'svelte';
    import { auth } from '$lib/api';

    onMount(() => {
        auth.login();
    });
</script>

<div class="flex items-center justify-center min-h-screen">
    <p class="text-gray-600">Redirecting to login...</p>
</div>