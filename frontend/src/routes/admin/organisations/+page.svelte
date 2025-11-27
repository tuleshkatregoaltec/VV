<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  interface Organisation {
    id: string;
    name: string;
    email_domain: string;
    max_users: number;
    active_user_count: number;
    is_active: boolean;
  }

  let organisations: Organisation[] = [];
  let loading = true;
  let error = '';

  async function fetchOrganisations() {
    loading = true;
    error = '';
    try {
      const res = await fetch('http://localhost:8000/api/admin/organisations', {
        credentials: 'include'
      });
      if (!res.ok) throw new Error('Failed to fetch organizations');
      organisations = await res.json();
    } catch (e: any) {
      error = e.message;
    } finally {
      loading = false;
    }
  }

  onMount(fetchOrganisations);
</script>

<div class="max-w-7xl mx-auto px-4 py-8">
  <div class="flex justify-between items-center mb-6">
    <h1 class="text-3xl font-bold">Organizations</h1>
    <button
      onclick={() => goto('/admin/organisations/new')}
      class="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700"
    >
      New Organization
    </button>
  </div>

  {#if loading}
    <div class="text-center py-12">
      <p class="text-gray-600">Loading organizations...</p>
    </div>
  {:else if error}
    <div class="bg-red-50 border border-red-200 rounded p-4">
      <p class="text-red-600">{error}</p>
    </div>
  {:else if organisations.length === 0}
    <div class="text-center py-12">
      <p class="text-gray-600">No organizations found. Create your first one!</p>
    </div>
  {:else}
    <div class="bg-white shadow-md rounded-lg overflow-hidden">
      <table class="min-w-full divide-y divide-gray-200">
        <thead class="bg-gray-50">
          <tr>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Name
            </th>
            <th class="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
              Domain
            </th>
            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
              Users
            </th>
            <th class="px-6 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
              Status
            </th>
            <th class="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
              Actions
            </th>
          </tr>
        </thead>
        <tbody class="bg-white divide-y divide-gray-200">
          {#each organisations as org}
            <tr class="hover:bg-gray-50">
              <td class="px-6 py-4 whitespace-nowrap">
                <div class="text-sm font-medium text-gray-900">{org.name}</div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap">
                <div class="text-sm text-gray-500">{org.email_domain}</div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-right">
                <div class="text-sm text-gray-900">
                  {org.active_user_count} / {org.max_users}
                </div>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-center">
                <span class="px-2 inline-flex text-xs leading-5 font-semibold rounded-full {org.is_active ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'}">
                  {org.is_active ? 'Active' : 'Inactive'}
                </span>
              </td>
              <td class="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                <button
                  onclick={() => goto(`/admin/organisations/${org.id}`)}
                  class="text-blue-600 hover:text-blue-900"
                >
                  View
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
