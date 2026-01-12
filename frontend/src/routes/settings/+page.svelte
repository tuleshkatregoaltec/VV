<script lang="ts">
    import { authStore } from '$lib/stores/auth.svelte';
    import { areaUnit } from '$lib/stores/preferences.svelte';
    import { getAreaUnitLabel } from '$lib/utils/units';

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
                    <div>
                        <span class="text-gray-700">Area unit</span>
                        <p class="text-xs text-gray-500">Display areas in square meters or square feet</p>
                    </div>
                    <div class="flex items-center gap-2">
                        <button
                            type="button"
                            onclick={() => areaUnit.current = 'sqm'}
                            class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {areaUnit.current === 'sqm' 
                                ? 'bg-primary text-white' 
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
                        >
                            sq.m
                        </button>
                        <button
                            type="button"
                            onclick={() => areaUnit.current = 'sqft'}
                            class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {areaUnit.current === 'sqft' 
                                ? 'bg-primary text-white' 
                                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}"
                        >
                            sq.ft
                        </button>
                    </div>
                </div>
            </div>
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
                        <span class="text-gray-500">Organization</span>
                        <span class="text-gray-900">{user.organization_name}</span>
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
