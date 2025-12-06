<script lang="ts">
  import { goto } from '$app/navigation';
  import { admin, ApiError } from '$lib/api';

  let name = '';
  let domain = '';
  let max_users = 5;
  let submitting = false;
  let error = '';

  async function handleSubmit(event: SubmitEvent) {
    event.preventDefault();
    submitting = true;
    error = '';

    const trimmedDomain = domain.trim();

    if (!name) {
      error = 'Organization name is required';
      submitting = false;
      return;
    }

    if (!trimmedDomain) {
      error = 'Domain is required';
      submitting = false;
      return;
    }

    try {
      const org = await admin.organizations.create({
        name,
        domain: trimmedDomain,
        max_users
      });

      goto(`/admin/organizations/${org.id}`);
    } catch (e) {
      error = e instanceof ApiError ? e.message : 'Failed to create organization';
    } finally {
      submitting = false;
    }
  }
</script>

<div class="max-w-2xl mx-auto px-4 py-8">
  <h1 class="text-3xl font-bold mb-6">Create New Organization</h1>

  <form onsubmit={handleSubmit} class="bg-white shadow-md rounded px-8 pt-6 pb-8">
    <div class="mb-4">
      <label class="block text-gray-700 text-sm font-bold mb-2" for="name">
        Organization Name
      </label>
      <input
        id="name"
        type="text"
        bind:value={name}
        class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
        placeholder="Acme Corp"
        required
      />
    </div>

    <div class="mb-4">
      <label class="block text-gray-700 text-sm font-bold mb-2" for="domain">
        Domain
      </label>
      <input
        id="domain"
        type="text"
        bind:value={domain}
        class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
        placeholder="acme.com"
        required
      />
      <p class="text-gray-600 text-xs mt-1">The email domain for this organization</p>
    </div>

    <div class="mb-6">
      <label class="block text-gray-700 text-sm font-bold mb-2" for="max_users">
        Max Users
      </label>
      <input
        id="max_users"
        type="number"
        bind:value={max_users}
        min="1"
        class="shadow appearance-none border rounded w-full py-2 px-3 text-gray-700 leading-tight focus:outline-none focus:shadow-outline"
        required
      />
    </div>

    {#if error}
      <div class="mb-4 bg-red-50 border border-red-200 rounded p-3">
        <p class="text-red-600 text-sm">{error}</p>
      </div>
    {/if}

    <div class="flex items-center justify-between">
      <button
        type="button"
        onclick={() => goto('/admin/organizations')}
        class="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline"
      >
        Cancel
      </button>
      <button
        type="submit"
        disabled={submitting}
        class="bg-blue-600 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded focus:outline-none focus:shadow-outline disabled:opacity-50"
      >
        {submitting ? 'Creating...' : 'Create Organization'}
      </button>
    </div>
  </form>
</div>
