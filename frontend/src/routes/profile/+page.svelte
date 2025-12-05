<script lang="ts">
    import { authStore } from '$lib/stores/auth.svelte';

    const user = $derived(authStore.user);
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
    <h1 class="text-3xl font-bold mb-8">Profile</h1>

    {#if user}
        <div class="bg-white shadow-md rounded-lg p-6">
            <h2 class="text-lg font-semibold mb-4">Account Details</h2>
            
            <div class="space-y-4">
                <div class="flex justify-between py-3 border-b border-gray-100">
                    <span class="text-gray-500">Full Name</span>
                    <span class="text-gray-900">{user.first_name} {user.last_name}</span>
                </div>
                <div class="flex justify-between py-3 border-b border-gray-100">
                    <span class="text-gray-500">Email</span>
                    <span class="text-gray-900">{user.email}</span>
                </div>
                <div class="flex justify-between py-3 border-b border-gray-100">
                    <span class="text-gray-500">Organisation</span>
                    <span class="text-gray-900">{user.organisation_name}</span>
                </div>
            </div>

            <button
                type="button"
                onclick={() => authStore.logout()}
                class="mt-6 bg-red-600 hover:bg-red-700 text-white font-medium py-2.5 px-6 rounded-lg transition-colors"
            >
                Sign Out
            </button>
        </div>
    {:else}
        <p class="text-gray-500">Loading...</p>
    {/if}
</div>