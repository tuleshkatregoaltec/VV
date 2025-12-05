<script lang="ts">
    import { authStore } from '$lib/stores/auth.svelte';

    const user = $derived(authStore.user);
</script>

<div class="max-w-3xl mx-auto px-4 py-8">
    <h1 class="text-3xl font-bold mb-8">Settings</h1>

    <div class="space-y-6">
        <!-- Notifications Section -->
        <div class="bg-white shadow-md rounded-lg p-6">
            <h2 class="text-lg font-semibold mb-4">Notifications</h2>
            <div class="space-y-4">
                <label class="flex items-center justify-between">
                    <span class="text-gray-700">Email notifications</span>
                    <input type="checkbox" checked class="w-5 h-5 text-primary rounded focus:ring-primary" disabled />
                </label>
                <label class="flex items-center justify-between">
                    <span class="text-gray-700">Weekly digest</span>
                    <input type="checkbox" class="w-5 h-5 text-primary rounded focus:ring-primary" disabled />
                </label>
            </div>
            <p class="text-sm text-gray-500 mt-4">Notification settings coming soon.</p>
        </div>

        <!-- Preferences Section -->
        <div class="bg-white shadow-md rounded-lg p-6">
            <h2 class="text-lg font-semibold mb-4">Preferences</h2>
            <div class="space-y-4">
                <div class="flex items-center justify-between">
                    <span class="text-gray-700">Default currency</span>
                    <span class="text-gray-900 font-medium">AED</span>
                </div>
                <div class="flex items-center justify-between">
                    <span class="text-gray-700">Area unit</span>
                    <span class="text-gray-900 font-medium">sq.ft</span>
                </div>
            </div>
            <p class="text-sm text-gray-500 mt-4">Preference customization coming soon.</p>
        </div>

        <!-- Account Section -->
        <div class="bg-white shadow-md rounded-lg p-6">
            <h2 class="text-lg font-semibold mb-4">Account</h2>
            {#if user}
                <div class="space-y-3 text-sm">
                    <div class="flex justify-between">
                        <span class="text-gray-500">Email</span>
                        <span class="text-gray-900">{user.email}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500">Organisation</span>
                        <span class="text-gray-900">{user.organisation_name}</span>
                    </div>
                </div>
            {/if}
            <div class="mt-6 pt-4 border-t border-gray-200">
                <button
                    type="button"
                    onclick={() => authStore.logout()}
                    class="text-red-600 hover:text-red-700 font-medium text-sm"
                >
                    Sign out of your account
                </button>
            </div>
        </div>
    </div>
</div>
