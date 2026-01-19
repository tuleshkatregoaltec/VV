<script lang="ts">
    import { logout, update_user_profile } from '$lib/api/auth';
    import { areaUnit } from '$lib/stores/preferences.svelte';
    import { currentUser, setUser } from '$lib/stores/user.svelte';

    let editingName = $state(false);
    let firstName = $state('');
    let lastName = $state('');
    let editError = $state('');
    let editSuccess = $state('');

    $effect(() => {
        if (currentUser.data && !editingName) {
            firstName = currentUser.data.first_name || '';
            lastName = currentUser.data.last_name || '';
        }
    });

    function handleNameEdit() {
        editError = '';
        editSuccess = '';

        if (!firstName.trim() || !lastName.trim()) {
            editError = 'Both first and last names are required';
            return;
        }

        const trimmedFirstName = firstName.trim();
        const trimmedLastName = lastName.trim();

        // Immediately update local user store
        if (currentUser.data) {
            setUser({
                ...currentUser.data,
                first_name: trimmedFirstName,
                last_name: trimmedLastName
            });
        }

        editSuccess = 'Profile updated successfully';
        editingName = false;

        setTimeout(() => {
            editSuccess = '';
        }, 3000);

        // Make the update request in the background
        update_user_profile(trimmedFirstName, trimmedLastName).then(result => {
            if (!result.success) {
                editError = result.error || 'Failed to sync profile changes';
            }
        });
    }

    function handleCancel() {
        editingName = false;
        editError = '';
        if (currentUser.data) {
            firstName = currentUser.data.first_name || '';
            lastName = currentUser.data.last_name || '';
        }
    }
</script>

<div class="min-h-screen bg-slate-50">
    <div class="max-w-3xl mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-slate-900 mb-8">Profile</h1>

        <div class="space-y-6">
            <!-- Account Details Section -->
            <div class="bg-white/80 backdrop-blur-sm shadow-sm rounded-lg p-6 border border-slate-200">
                <div class="flex items-center justify-between mb-4">
                    <h2 class="text-lg font-semibold text-slate-900">Account Details</h2>
                    {#if !editingName}
                        <button
                            type="button"
                            onclick={() => editingName = true}
                            class="text-sm text-primary hover:text-primary/80 font-medium transition-colors"
                        >
                            Edit Name
                        </button>
                    {/if}
                </div>

                {#if editingName}
                    <div class="space-y-4">
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">First Name</label>
                            <input
                                type="text"
                                bind:value={firstName}
                                class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                            />
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-slate-700 mb-1">Last Name</label>
                            <input
                                type="text"
                                bind:value={lastName}
                                class="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/50"
                            />
                        </div>

                        {#if editError}
                            <p class="text-sm text-red-600">{editError}</p>
                        {/if}

                        <div class="flex gap-2 pt-2">
                            <button
                                type="button"
                                onclick={handleNameEdit}
                                class="px-4 py-2 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium"
                            >
                                Save
                            </button>
                            <button
                                type="button"
                                onclick={handleCancel}
                                class="px-4 py-2 bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300 transition-colors text-sm font-medium"
                            >
                                Cancel
                            </button>
                        </div>
                    </div>
                {:else}
                    {#if currentUser.data}
                        <div class="space-y-3 text-sm">
                            <div class="flex justify-between">
                                <span class="text-slate-500">Full Name</span>
                                <span class="text-slate-900">{currentUser.data.first_name} {currentUser.data.last_name}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-slate-500">Email</span>
                                <span class="text-slate-900">{currentUser.data.email}</span>
                            </div>
                            <div class="flex justify-between">
                                <span class="text-slate-500">Organization</span>
                                <span class="text-slate-900">{currentUser.data.organization_name}</span>
                            </div>
                        </div>
                    {:else}
                        <p class="text-slate-500">Loading...</p>
                    {/if}
                {/if}

                {#if editSuccess}
                    <p class="text-sm text-green-600 mt-3">{editSuccess}</p>
                {/if}
            </div>

            <!-- Notifications Section -->
            <div class="bg-white/80 backdrop-blur-sm shadow-sm rounded-lg p-6 border border-slate-200">
                <h2 class="text-lg font-semibold text-slate-900 mb-4">Notifications</h2>
                <div class="space-y-4">
                    <label class="flex items-center justify-between">
                        <span class="text-slate-700">Email notifications</span>
                        <input type="checkbox" checked class="w-5 h-5 text-primary rounded focus:ring-primary" disabled />
                    </label>
                    <label class="flex items-center justify-between">
                        <span class="text-slate-700">Weekly digest</span>
                        <input type="checkbox" class="w-5 h-5 text-primary rounded focus:ring-primary" disabled />
                    </label>
                </div>
                <p class="text-sm text-slate-500 mt-4">Notification settings coming soon.</p>
            </div>

            <!-- Preferences Section -->
            <div class="bg-white/80 backdrop-blur-sm shadow-sm rounded-lg p-6 border border-slate-200">
                <h2 class="text-lg font-semibold text-slate-900 mb-4">Preferences</h2>
                <div class="space-y-4">
                    <div class="flex items-center justify-between">
                        <div>
                            <span class="text-slate-700">Area unit</span>
                            <p class="text-xs text-slate-500">Display areas in square meters or square feet</p>
                        </div>
                        <div class="flex items-center gap-2">
                            <button
                                type="button"
                                onclick={() => areaUnit.current = 'sqm'}
                                class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {areaUnit.current === 'sqm'
                                    ? 'bg-primary text-white'
                                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
                            >
                                sq.m
                            </button>
                            <button
                                type="button"
                                onclick={() => areaUnit.current = 'sqft'}
                                class="px-3 py-1.5 text-sm font-medium rounded-lg transition-colors {areaUnit.current === 'sqft'
                                    ? 'bg-primary text-white'
                                    : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
                            >
                                sq.ft
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Account Actions Section -->
            <div class="bg-white/80 backdrop-blur-sm shadow-sm rounded-lg p-6 border border-slate-200">
                <button
                    type="button"
                    onclick={() => logout()}
                    class="text-red-600 hover:text-red-700 font-medium text-sm"
                >
                    Sign out of your account
                </button>
            </div>
        </div>
    </div>
</div>