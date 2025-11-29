<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  interface User {
    id: string;
    email: string;
    first_name: string;
    last_name: string;
    is_active: boolean;
    created_at: string;
    last_login: string | null;
  }

  interface Organisation {
    id: string;
    name: string;
    email_domain: string;
    max_users: number;
    is_active: boolean;
    active_user_count: number;
  }

  let organisation: Organisation | null = null;
  let users: User[] = [];
  let loading = true;
  let error = '';
  let saving = false;
  let deleting = false;
  let showDeleteConfirm = false;

  // Editable fields
  let max_users: number;
  let is_active: boolean;

  async function fetchOrganisation() {
    loading = true;
    error = '';
    const orgId = page.params.id;

    try {
      const res = await fetch(`http://localhost:8000/api/admin/organisations/${orgId}`, {
        credentials: 'include'
      });

      if (!res.ok) throw new Error('Failed to fetch organization');

      const data = await res.json();
      organisation = data.organisation;
      users = data.users;
      max_users = organisation.max_users;
      is_active = organisation.is_active;
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  async function saveChanges() {
    if (!organisation) return;

    saving = true;
    error = '';

    try {
      const res = await fetch(`http://localhost:8000/api/admin/organisations/${organisation.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          max_users,
          is_active
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to update organization');
      }

      const updated = await res.json();
      organisation = updated;
      alert('Organization updated successfully!');
    } catch (e: any) {
      error = e.message;
    } finally {
      saving = false;
    }
  }

  async function toggleUserActive(user: User) {
    try {
      const res = await fetch(`http://localhost:8000/api/admin/users/${user.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({
          is_active: !user.is_active
        })
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to update user');
      }

      // Update local state
      user.is_active = !user.is_active;
      users = [...users]; // Trigger reactivity

      // Refetch to update active user count
      await fetchOrganisation();
    } catch (e: any) {
      alert(`Error updating user: ${e.message}`);
    }
  }

  async function deleteOrganisation() {
    if (!organisation) return;

    deleting = true;
    error = '';

    try {
      const res = await fetch(`http://localhost:8000/api/admin/organisations/${organisation.id}`, {
        method: 'DELETE',
        credentials: 'include'
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to delete organization');
      }

      // Redirect to organizations list
      goto('/admin/organisations');
    } catch (e: any) {
      error = e.message;
      deleting = false;
      showDeleteConfirm = false;
    }
  }

  function formatDate(dateStr: string | null) {
    if (!dateStr) return 'Never';
    return new Date(dateStr).toLocaleDateString();
  }

  function fullName(user: User) {
    const name = `${user.first_name || ''} ${user.last_name || ''}`.trim();
    return name || user.email;
  }

  onMount(fetchOrganisation);
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
  {#if loading}
    <div class="text-center py-12">
      <p class="text-gray-600">Loading organization...</p>
    </div>
  {:else if error && !organisation}
    <div class="bg-red-50 border border-red-200 rounded p-4">
      <p class="text-red-600">{error}</p>
      <button
        on:click={() => goto('/admin/organisations')}
        class="mt-4 text-blue-600 hover:text-blue-800"
      >
        ← Back to Organizations
      </button>
    </div>
  {:else if organisation}
    <div class="mb-6 flex justify-between items-start">
      <div>
        <button
          on:click={() => goto('/admin/organisations')}
          class="text-blue-600 hover:text-blue-800 mb-4"
        >
          ← Back to Organizations
        </button>
        <h1 class="text-3xl font-bold">{organisation.name}</h1>
        <p class="text-gray-600 mt-2">Domain: {organisation.email_domain}</p>
      </div>
      
      <button
        on:click={() => (showDeleteConfirm = true)}
        class="bg-red-600 hover:bg-red-700 text-white font-bold py-2 px-4 rounded"
      >
        Delete Organization
      </button>
    </div>

    <div class="bg-white shadow-md rounded-lg p-6 mb-6">
      <h2 class="text-xl font-semibold mb-4">Settings</h2>

      <div class="grid grid-cols-2 gap-4 mb-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Max Users
          </label>
          <input
            type="number"
            bind:value={max_users}
            min="1"
            class="shadow-sm border rounded w-full py-2 px-3 text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label class="block text-sm font-medium text-gray-700 mb-2">
            Active Users
          </label>
          <p class="py-2 px-3 text-gray-900">{organisation.active_user_count} / {organisation.max_users}</p>
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
        on:click={saveChanges}
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
              <tr class="hover:bg-gray-50">
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm font-medium text-gray-900">{fullName(user)}</div>
                </td>
                <td class="px-6 py-4 whitespace-nowrap">
                  <div class="text-sm text-gray-500">{user.email}</div>
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
                    on:click={() => toggleUserActive(user)}
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
        Are you sure you want to delete <strong>{organisation?.name}</strong>? This action cannot be undone and will delete all associated users.
      </p>
      <div class="flex justify-end gap-3">
        <button
          on:click={() => (showDeleteConfirm = false)}
          disabled={deleting}
          class="px-4 py-2 bg-gray-300 hover:bg-gray-400 rounded disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          on:click={deleteOrganisation}
          disabled={deleting}
          class="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded disabled:opacity-50"
        >
          {deleting ? 'Deleting...' : 'Delete'}
        </button>
      </div>
    </div>
  </div>
{/if}
