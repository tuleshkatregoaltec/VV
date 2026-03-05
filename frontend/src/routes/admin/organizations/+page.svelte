<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { admin, type OrgListItem } from '$lib/api/admin';
    import { ApiError } from '$lib/api/client';
    import CreateUserModal from '$lib/components/admin/CreateUserModal.svelte';
    import ConfirmModal from '$lib/components/ui/ConfirmModal.svelte';

    let orgs = $state<OrgListItem[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateUser = $state(false);
    let activatingOrgId = $state<string | null>(null);
    let deletingOrgId = $state<string | null>(null);
    let confirmDeleteOrg = $state<OrgListItem | null>(null);

    async function fetchOrgs() {
        loading = true;
        error = '';
        try {
            orgs = await admin.organizations.list();
        } catch (e) {
            error = e instanceof ApiError ? e.message : 'Failed to load organizations';
        } finally {
            loading = false;
        }
    }

    async function activateOrg(org: OrgListItem) {
        activatingOrgId = org.id;
        try {
            const updated = await admin.organizations.setSubscription(org.id, 'active');
            const idx = orgs.findIndex((o) => o.id === org.id);
            if (idx !== -1) orgs[idx] = updated;
            orgs = [...orgs];
        } catch (e) {
            alert(e instanceof ApiError ? e.message : 'Failed to activate');
        } finally {
            activatingOrgId = null;
        }
    }

    async function deleteOrg() {
        if (!confirmDeleteOrg) return;
        deletingOrgId = confirmDeleteOrg.id;
        try {
            await admin.organizations.delete(confirmDeleteOrg.id);
            orgs = orgs.filter((o) => o.id !== confirmDeleteOrg!.id);
            confirmDeleteOrg = null;
        } catch (e) {
            alert(e instanceof ApiError ? e.message : 'Failed to delete');
        } finally {
            deletingOrgId = null;
        }
    }

    function statusBadge(status: string) {
        switch (status) {
            case 'active': return 'bg-green-100 text-green-800';
            case 'trialing': return 'bg-blue-100 text-blue-800';
            case 'past_due': return 'bg-orange-100 text-orange-800';
            case 'canceled': return 'bg-red-100 text-red-800';
            default: return 'bg-gray-100 text-gray-600';
        }
    }

    function formatDate(d: string) {
        return new Date(d).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
    }

    onMount(fetchOrgs);
</script>

<div class="max-w-7xl mx-auto px-4 py-6">
    <div class="flex justify-between items-center mb-6">
        <h1 class="text-2xl font-bold text-gray-900">Organizations</h1>
        <button
            onclick={() => (showCreateUser = true)}
            class="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
        >
            + Create User
        </button>
    </div>

    {#if loading}
        <div class="text-center py-16 text-gray-400">Loading...</div>
    {:else if error}
        <div class="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700 text-sm">{error}</div>
    {:else if orgs.length === 0}
        <div class="text-center py-16 text-gray-400">No organizations yet.</div>
    {:else}
        <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <table class="min-w-full divide-y divide-gray-100">
                <thead>
                    <tr class="bg-gray-50">
                        <th class="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Organization</th>
                        <th class="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Owner</th>
                        <th class="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Members</th>
                        <th class="px-5 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wider">Subscription</th>
                        <th class="px-5 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wider">Created</th>
                        <th class="px-5 py-3"></th>
                    </tr>
                </thead>
                <tbody class="divide-y divide-gray-100">
                    {#each orgs as org}
                        <tr class="hover:bg-gray-50 transition-colors">
                            <td class="px-5 py-4">
                                <span class="font-medium text-gray-900 text-sm">{org.name}</span>
                            </td>
                            <td class="px-5 py-4 text-sm text-gray-500">{org.owner_email}</td>
                            <td class="px-5 py-4 text-center text-sm text-gray-600">
                                {org.user_count} / {org.max_users}
                            </td>
                            <td class="px-5 py-4 text-center">
                                <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold {statusBadge(org.subscription_status)}">
                                    {org.subscription_status}
                                </span>
                            </td>
                            <td class="px-5 py-4 text-sm text-gray-400">{formatDate(org.created_at)}</td>
                            <td class="px-5 py-4">
                                <div class="flex items-center justify-end gap-2">
                                    {#if org.subscription_status !== 'active'}
                                        <button
                                            onclick={() => activateOrg(org)}
                                            disabled={activatingOrgId === org.id}
                                            class="text-xs font-medium text-green-700 bg-green-50 hover:bg-green-100 border border-green-200 px-2.5 py-1 rounded-md transition-colors disabled:opacity-50"
                                        >
                                            {activatingOrgId === org.id ? '...' : 'Activate'}
                                        </button>
                                    {/if}
                                    <button
                                        onclick={() => goto(`/admin/organizations/${org.id}`)}
                                        class="text-xs font-medium text-blue-600 hover:text-blue-800 px-2.5 py-1 rounded-md hover:bg-blue-50 transition-colors"
                                    >
                                        View →
                                    </button>
                                    <button
                                        onclick={() => (confirmDeleteOrg = org)}
                                        class="text-xs font-medium text-red-500 hover:text-red-700 px-2.5 py-1 rounded-md hover:bg-red-50 transition-colors"
                                    >
                                        Delete
                                    </button>
                                </div>
                            </td>
                        </tr>
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}
</div>

<CreateUserModal
    open={showCreateUser}
    {orgs}
    onClose={() => (showCreateUser = false)}
    onCreated={fetchOrgs}
/>

<ConfirmModal
    open={confirmDeleteOrg !== null}
    title="Delete Organization"
    message={`Delete '${confirmDeleteOrg?.name}'? This removes the org and all its data. Users will lose access.`}
    confirmText={deletingOrgId ? 'Deleting...' : 'Delete'}
    confirmVariant="danger"
    onConfirm={deleteOrg}
    onCancel={() => (confirmDeleteOrg = null)}
/>
