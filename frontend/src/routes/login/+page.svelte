<script lang="ts">
    import { onMount } from 'svelte';

    onMount(() => {
        // Redirect to backend auth endpoint
        window.location.href = 'http://localhost:8000/auth/login';
    });
</script>

<div class="flex items-center justify-center min-h-screen">
    <p class="text-gray-600">Redirecting to login...</p>
</div>