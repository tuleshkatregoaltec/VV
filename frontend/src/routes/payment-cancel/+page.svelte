<script lang="ts">
import { resolve } from '$app/paths'
import AuthFlowShell from '$lib/components/auth/AuthFlowShell.svelte'
</script>

<svelte:head>
	<title>Payment cancelled - Vitevue</title>
</svelte:head>

<AuthFlowShell
	title="Payment cancelled"
	eyebrow="Workspace setup"
	sideAccent="Billing"
	sideTitle="Your workspace is not active yet."
	contentWidthClass="max-w-xl"
	sectionWidthClass="lg:max-w-xl"
>
	<svelte:fragment slot="side">
		<div class="rounded-lg border border-[rgba(246,241,231,0.14)] bg-[color:rgba(246,241,231,0.05)] p-5">
			<p class="font-mono text-[10px] font-medium uppercase tracking-[0.16em] text-on-navy-muted">
				No payment captured
			</p>
		</div>
	</svelte:fragment>

	<div class="space-y-5">
		<div class="rounded-lg border border-[rgba(165,90,19,0.2)] bg-warning-bg p-5">
			<p class="text-sm font-semibold text-warning">Checkout was cancelled</p>
		</div>

		<div class="flex flex-col gap-3 sm:flex-row">
			<a
				href={resolve('/setup')}
				class="flex-1 rounded-md bg-action px-5 py-3 text-center text-sm font-semibold text-on-action transition hover:bg-action-hover"
			>
				Return to setup
			</a>
			<a
				href="mailto:contact@vitevue.com"
				class="rounded-md border border-strong px-5 py-3 text-center text-sm font-semibold text-fg-2 transition hover:bg-panel"
			>
				Contact support
			</a>
		</div>
	</div>
</AuthFlowShell>
