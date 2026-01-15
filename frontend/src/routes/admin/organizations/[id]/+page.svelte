<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { admin, type Organization, type OrganizationUser } from '$lib/api/admin';
  import { ApiError } from '$lib/api/client';
  import UserDetailsModal from '$lib/components/admin/UserDetailsModal.svelte';

  export const prerender = false;

  let organization = $state<Organization | null>(null);
  let users = $state<OrganizationUser[]>([]);
  let loading = $state(true);
  let error = $state('');
  let saving = $state(false);
  let deleting = $state(false);
  let showDeleteConfirm = $state(false);

  // Editable fields - initialized with defaults, updated after fetch
  let max_users = $state(0);
  let is_active = $state(false);

  // Modal state
  let selectedUser = $state<OrganizationUser | null>(null);
  let showUserModal = $state(false);

  async function fetchOrganization() {
    loading = true;
    error = '';
    const orgId = page.params.id;

    if (!orgId) {
      error = 'Organization ID is required';
      loading = false;
      return;
    }

    try {
      const data = await admin.organizations.get(orgId);
      organization = data.organization;
      users = data.users;
      max_users = organization.max_users;
      is_active = organization.is_active;
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Failed to fetch organization';
    } finally {
      loading = false;
    }
  }

  async function saveChanges() {
    if (!organization) return;

    saving = true;
    error = '';

    try {
      const updated = await admin.organizations.update(organization.id, {
        max_users,
        is_active
      });
      organization = updated;
      alert('Organization updated successfully!');
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Failed to update organization';
    } finally {
      saving = false;
    }
  }

  async function toggleUserActive(user: OrganizationUser) {
    try {
      await admin.users.update(user.id, {
        is_active: !user.is_active
      });

      // Update local state
      user.is_active = !user.is_active;
      users = [...users]; // Trigger reactivity

      // Refetch to update active user count
      await fetchOrganization();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : 'Failed to update user';
      alert(`Error updating user: ${message}`);
    }
  }

  async function deleteOrganization() {
    if (!organization) return;

    deleting = true;
    error = '';

    try {
      await admin.organizations.delete(organization.id);
      // Redirect to organizations list
      goto('/admin/organizations');
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Failed to delete organization';
      deleting = false;
      showDeleteConfirm = false;
    }
  }

  function formatDate(dateStr: string | null) {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleDateString();
  }

  function fullName(user: OrganizationUser) {
    const name = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    return name || user.email;
  }

  function openUserModal(user: OrganizationUser) {
    selectedUser = user;
    showUserModal = true;
  }

  function closeUserModal() {
    showUserModal = false;
    selectedUser = null;
  }

  async function handleUserUpdated() {
    await fetchOrganization();
  }

  function getUsageColor(percentage: number): string {
    if (percentage >= 90) return 'bg-red-500';
    if (percentage >= 70) return 'bg-yellow-500';
    return 'bg-green-500';
  }

  function getUsageTextColor(percentage: number): string {
    if (percentage >= 90) return 'text-red-700';
    if (percentage >= 70) return 'text-yellow-700';
    return 'text-green-700';
  }

  onMount(fetchOrganization);
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
  {#if loading}
    <div class="text-center py-12">
      <p class="text-gray-600">Loading organization...</p>
    </div>
  {:else if error && !organization}
    <div class="bg-red-50 border border-red-200 rounded p-4">
      <p class="text-red-600">{error}</p>
      <button
        onclick={() => goto('/admin/organizations')}
        class="mt-4 text-blue-600 hover:text-blue-800"
      >
        ← Back to Organizations
      </button>
    </div>
  {:else if organization}
    <div class="mb-6 flex justify-between items-start">
      <div>
        <button
          onclick={() => goto('/admin/organizations')}
          class="text-blue-600 hover:text-blue-800 mb-4"
        >
          ← Back to Organizations
        </button>
        <h1 class="text-3xl font-bold">{organization.name}</h1>
        <p class="text-gray-600 mt-2">Domain: {organization.email_domain}</p>
      </div>
      
      <button
        onclick={() => (showDeleteConfirm = true)}
        class="bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded"
      >
        Delete Organization
      </button>
    </div>

    <div class="bg-white shadow-md rounded-lg p-6 mb-6">
      <h2 class="text-xl font-semibold mb-4">Settings</h2>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label for="max-users-input" class="block text-sm font-medium text-gray-700 mb-2">
            Max Users
          </label>
          <input
            id="max-users-input"
            type="number"
            bind:value={max_users}
            min="1"
            class="shadow-sm border rounded w-full py-2 px-3 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <span class="block text-sm font-medium text-gray-700 mb-2">
            Active Users
          </span>
          <p class="py-2 px-3 text-gray-900">{organization.active_user_count} / {organization.max_users}</p>
        </div>
      </div>

      <div class="mb-4">
        <label class="flex items-center">
          <input type="checkbox" bind:checked={is_active} class="mr-2" />
          <span class="text-sm font-medium text-gray-700">Organization is active</span>
        </label>
      </div>

      {#if error}
        <div class="mb-4 bg-red-50 border border-red-200 rounded p-3">
          <p class="text-red-600 text-sm">{error}</p>
        </div>
      {/if}

      <button
        onclick={saveChanges}
        disabled={saving}
        class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded disabled:opacity-50"
      >
        {saving ? 'Saving...' : 'Save Changes'}
      </button>
    </div>

    <div class="bg-white shadow-md rounded-lg overflow-hidden">
      <div class="px-6 py-4 border-b border-gray-200">
        <h2 class="text-xl font-semibold">Users ({users.length})</h2>
      </div>

      {#if users.length === 0}
        <div class="px-6 py-8 text-center text-gray-600">
          No users in this organization yet.
        </div>
      {:else}
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50">
            <tr>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Name
              </th>
              <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                Email
              </th>
              <th class="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                Token Usage
              </th>
              <th class="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                Status
              </th>
              <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Last Login
              </th>
              <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            {#each users as user}
              <tr class="hover:bg-gray-50 cursor-pointer" onclick={() => openUserModal(user)}>
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm font-medium text-gray-900">{fullName(user)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm text-gray-500">{user.email}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <!-- Token Usage Indicator -->
                  <div class="flex flex-col items-center">
                    <span class="text-xs font-medium mb-1 {getUsageTextColor(user.usage_percentage)}">
                      {user.usage_percentage.toFixed(0)}%
                    </span>
                    <div class="w-full max-w-[80px] bg-gray-200 rounded-full h-2 overflow-hidden">
                      <div
                        class="h-full {getUsageColor(user.usage_percentage)}"
                        style="width: {Math.min(user.usage_percentage, 100)}%"
                      ></div>
                    </div>
                  </div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-center">
                  <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {user.is_active ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'}">
                    {user.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm text-gray-500">
                  {formatDate(user.last_login)}
                </td>
                <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                  <button
                    onclick={(e) => {
                      e.stopPropagation();
                      toggleUserActive(user);
                    }}
                    class="text-blue-600 hover:text-blue-900"
                  >
                    {user.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </div>
  {/if}
</div>

<!-- Delete Confirmation Modal -->
{#if showDeleteConfirm}
  <div class="fixed inset-0 bg-gray-600 bg-opacity-50 overflow-y-auto h-full w-full flex items-center justify-center z-50">
    <div class="bg-white rounded-lg shadow-xl p-6 max-w-md mx-4">
      <h3 class="text-lg font-bold mb-4">Confirm Delete</h3>
      <p class="text-gray-700 mb-6">
        Are you sure you want to delete <strong>{organization?.name}</strong>? This action cannot be undone and will delete all associated users.
      </p>
      <div class="flex justify-end gap-3">
        <button
          onclick={() => (showDeleteConfirm = false)}
          disabled={deleting}
          class="px-4 py-2 bg-gray-300 hover:bg-gray-400 rounded disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          onclick={deleteOrganization}
          disabled={deleting}
          class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded disabled:opacity-50"
        >
          {deleting ? 'Deleting...' : 'Delete'}
        </button>
      </div>
    </div>
  </div>
{/if}

<!-- User Details Modal -->
<UserDetailsModal
  open={showUserModal}
  user={selectedUser}
  onClose={closeUserModal}
  onUpdated={handleUserUpdated}
/>
