<script lang="ts">
    import { logout } from '$lib/api/auth';
    import { currentUser } from '$lib/stores/user.svelte';
</script>

<div class="min-h-screen bg-slate-50">
    <div class="max-w-7xl mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-slate-900 mb-8">Profile</h1>

        {#if currentUser.data}
            <div class="bg-white/80 backdrop-blur-sm shadow-sm rounded-lg p-6 border border-slate-200">
                <h2 class="text-lg font-semibold text-slate-900 mb-4">Account Details</h2>

                <div class="space-y-4">
                    <div class="flex justify-between py-3 border-b border-slate-100">
                        <span class="text-slate-500">Full Name</span>
                        <span class="text-slate-900">{currentUser.data.first_name} {currentUser.data.last_name}</span>
                    </div>
                    <div class="flex justify-between py-3 border-b border-slate-100">
                        <span class="text-slate-500">Email</span>
                        <span class="text-slate-900">{currentUser.data.email}</span>
                    </div>
                    <div class="flex justify-between py-3 border-b border-slate-100">
                        <span class="text-slate-500">Organization</span>
                        <span class="text-slate-900">{currentUser.data.organization_name}</span>
                    </div>
                </div>

                <button
                    type="button"
                    onclick={() => logout()}
                    class="mt-6 bg-red-600 hover:bg-red-700 text-white font-medium py-2.5 px-6 rounded-lg transition-colors shadow-sm"
                >
                    Sign Out
                </button>
            </div>
        {:else}
            <p class="text-slate-500">Loading...</p>
        {/if}
    </div>
</div>