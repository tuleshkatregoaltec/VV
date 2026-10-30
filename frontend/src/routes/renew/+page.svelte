<script lang="ts">
import { goto } from '$app/navigation'
import { resolve } from '$app/paths'
import { getCustomerPortalUrl } from '$lib/api/organization'
import AccountContextBar from '$lib/components/auth/AccountContextBar.svelte'
import AuthFlowShell from '$lib/components/auth/AuthFlowShell.svelte'
import { currentUser } from '$lib/stores/user.svelte'

let user = $derived(currentUser.data)
let error = $state('')
let processingRenewal = $state(false)

function getStatusMessage() {
	if (!user) return ''

	switch (user.subscription_status) {
		case 'past_due':
			return 'Subscription payment is past due.'
		case 'canceled':
			return 'Subscription canceled.'
		case 'incomplete':
			return 'Subscription setup is incomplete.'
		case null:
		case 'none':
			return 'No active subscription.'
		default:
			return 'Subscription inactive.'
	}
}

function getOwnerActionMessage() {
	return user?.subscription_status === 'past_due'
		? 'Update the payment method to restore team access.'
		: 'Renew billing to restore team access.'
}

async function handleManageSubscription() {
	processingRenewal = true
	error = ''
	try {
		const result = await getCustomerPortalUrl()
		window.location.href = result.url
	} catch (err: unknown) {
		error = err instanceof Error ? err.message : 'Could not open subscription management'
		processingRenewal = false
	}
}
</script>

<svelte:head>
	<title>Subscription Renewal Required - Vitevue</title>
</svelte:head>

<AuthFlowShell
	title={user?.is_owner ? 'Restore your workspace access' : 'Workspace subscription inactive'}
	description={getStatusMessage()}
	eyebrow="Billing recovery"
	sideAccent="Billing"
	sideTitle="Restore access to your workspace."
>
	<svelte:fragment slot="account">
		<AccountContextBar email={user?.email} redirectTo="/auth" />
	</svelte:fragment>

	<svelte:fragment slot="side">
		<div class="space-y-4 rounded-lg border border-[rgba(246,241,231,0.14)] bg-[color:rgba(246,241,231,0.05)] p-5">
			<div class="rounded-lg border border-[rgba(246,241,231,0.14)] bg-[color:rgba(246,241,231,0.05)] p-4">
				<p class="text-xs font-semibold uppercase tracking-[0.22em] text-on-navy-muted">Organization</p>
				<p class="mt-3 text-2xl font-semibold text-white">
					{user?.organization_name || 'Workspace'}
				</p>
				<p class="mt-2 text-sm leading-6 text-on-navy-muted">
					{user?.is_owner ? 'Owner' : 'Member'}
				</p>
			</div>
			<div
				class="rounded-md border border-[rgba(246,241,231,0.12)] bg-[color:rgba(246,241,231,0.04)] px-4 py-4 text-sm leading-6 text-on-navy"
			>
				{#if user?.is_owner}
					{getOwnerActionMessage()}
				{:else}
					Only the owner can restore billing.
				{/if}
			</div>
		</div>
	</svelte:fragment>

	{#if error}
		<div class="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
			{error}
		</div>
	{/if}

	<div class="space-y-5">
		{#if user?.is_owner}
			<div class="flex flex-col gap-3 sm:flex-row">
				{#if user.subscription_status === 'past_due' || user.subscription_status === 'canceled'}
					<button
						type="button"
						onclick={handleManageSubscription}
						disabled={processingRenewal}
						class="flex-1 rounded-md bg-action px-5 py-3 text-sm font-semibold text-on-action transition hover:bg-action-hover disabled:cursor-not-allowed disabled:opacity-50"
					>
						{processingRenewal ? 'Opening billing portal...' : 'Manage subscription'}
					</button>
				{:else}
					<button
						type="button"
						onclick={() => goto(resolve('/setup'))}
						class="flex-1 rounded-md bg-action px-5 py-3 text-sm font-semibold text-on-action transition hover:bg-action-hover"
					>
						Complete organization setup
					</button>
				{/if}
				<a
					href="mailto:contact@vitevue.com"
					class="rounded-md border border-strong px-5 py-3 text-center text-sm font-semibold text-fg-2 transition hover:bg-panel"
				>
					Contact support
				</a>
			</div>
		{:else}
			<div class="rounded-lg border border-info-border bg-info-bg p-6">
				<p class="text-sm font-semibold text-fg-1">Contact your organization owner</p>
				<p class="mt-2 text-sm leading-6 text-info">
					Only the organization owner can restore billing.
				</p>
			</div>
		{/if}
	</div>
</AuthFlowShell>
