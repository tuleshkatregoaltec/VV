<script lang="ts">
import { admin, type CreateUserRequest, type OrgListItem } from '$lib/api/admin'
import { ApiError } from '$lib/api/client'
import Modal from '$lib/components/ui/Modal.svelte'

let {
	open = false,
	orgs = [],
	onClose,
	onCreated
}: {
	open: boolean
	orgs: OrgListItem[]
	onClose: () => void
	onCreated: () => void
} = $props()

let email = $state('')
let password = $state('')
let firstName = $state('')
let lastName = $state('')
let orgMode = $state<'new' | 'existing'>('new')
let newOrgName = $state('')
let existingOrgId = $state('')
let tokenLimit = $state(100000)
let submitting = $state(false)
let error = $state('')
let success = $state('')

function reset() {
	email = ''
	password = ''
	firstName = ''
	lastName = ''
	orgMode = 'new'
	newOrgName = ''
	existingOrgId = orgs[0]?.id ?? ''
	tokenLimit = 100000
	error = ''
	success = ''
}

$effect(() => {
	if (open) {
		reset()
		existingOrgId = orgs[0]?.id ?? ''
	}
})

async function submit() {
	error = ''
	success = ''

	if (!email || !password || !firstName || !lastName) {
		error = 'All fields are required.'
		return
	}
	if (orgMode === 'new' && !newOrgName.trim()) {
		error = 'Organization name is required.'
		return
	}
	if (orgMode === 'existing' && !existingOrgId) {
		error = 'Please select an organization.'
		return
	}

	submitting = true
	try {
		const payload: CreateUserRequest = {
			email,
			password,
			first_name: firstName,
			last_name: lastName,
			org_mode: orgMode,
			org_name: orgMode === 'new' ? newOrgName.trim() : undefined,
			org_id: orgMode === 'existing' ? existingOrgId : undefined,
			daily_token_limit: tokenLimit
		}
		const result = await admin.users.create(payload)
		success = `Created ${result.email} in "${result.organization_name}"`
		onCreated()
		setTimeout(() => {
			onClose()
		}, 1500)
	} catch (e) {
		error = e instanceof ApiError ? e.message : 'Failed to create user'
	} finally {
		submitting = false
	}
}
</script>

<Modal {open} {onClose} title="Create User" size="md">
	<div class="space-y-4">
		<!-- Name row -->
		<div class="grid grid-cols-2 gap-3">
			<div>
				<label class="block text-xs font-medium text-gray-500 mb-1">First Name</label>
				<input
					type="text"
					bind:value={firstName}
					placeholder="Jane"
					class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>
			<div>
				<label class="block text-xs font-medium text-gray-500 mb-1">Last Name</label>
				<input
					type="text"
					bind:value={lastName}
					placeholder="Smith"
					class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
			</div>
		</div>

		<!-- Email -->
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1">Email</label>
			<input
				type="email"
				bind:value={email}
				placeholder="jane@example.com"
				class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
			/>
		</div>

		<!-- Password -->
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1">Password</label>
			<input
				type="password"
				bind:value={password}
				placeholder="Temporary password"
				class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
			/>
		</div>

		<!-- Org mode toggle -->
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-2">Organization</label>
			<div class="flex gap-2 mb-3">
				<button
					type="button"
					onclick={() => (orgMode = 'new')}
					class="flex-1 py-1.5 text-sm rounded-lg border transition-colors
                        {orgMode === 'new'
						? 'bg-blue-600 text-white border-blue-600'
						: 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}"
				>
					New org
				</button>
				<button
					type="button"
					onclick={() => (orgMode = 'existing')}
					class="flex-1 py-1.5 text-sm rounded-lg border transition-colors
                        {orgMode === 'existing'
						? 'bg-blue-600 text-white border-blue-600'
						: 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}"
				>
					Existing org
				</button>
			</div>

			{#if orgMode === 'new'}
				<input
					type="text"
					bind:value={newOrgName}
					placeholder="Organization name"
					class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
				/>
				<p class="text-xs text-gray-400 mt-1">Subscription will be set to active automatically.</p>
			{:else}
				<select
					bind:value={existingOrgId}
					class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
				>
					{#each orgs as org (org.id)}
						<option value={org.id}>{org.name} ({org.subscription_status})</option>
					{/each}
				</select>
				<p class="text-xs text-gray-400 mt-1">User will be added as a member.</p>
			{/if}
		</div>

		<!-- Token limit -->
		<div>
			<label class="block text-xs font-medium text-gray-500 mb-1">Daily Token Limit</label>
			<input
				type="number"
				bind:value={tokenLimit}
				min="0"
				step="10000"
				class="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
			/>
		</div>

		{#if error}
			<p class="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
				{error}
			</p>
		{/if}
		{#if success}
			<p class="text-sm text-green-700 bg-green-50 border border-green-200 rounded-lg px-3 py-2">
				{success}
			</p>
		{/if}

		<div class="flex justify-end gap-3 pt-2">
			<button
				type="button"
				onclick={onClose}
				disabled={submitting}
				class="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors disabled:opacity-50"
			>
				Cancel
			</button>
			<button
				type="button"
				onclick={submit}
				disabled={submitting}
				class="px-4 py-2 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg disabled:opacity-50 transition-colors"
			>
				{submitting ? 'Creating...' : 'Create User'}
			</button>
		</div>
	</div>
</Modal>
