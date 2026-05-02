<script lang="ts">
import { logout } from '$lib/api/auth'

let {
	show
}: {
	show: boolean
} = $props()

function handleLogout() {
	logout()
}
</script>

{#if show}
	<div class="space-y-1 border-t border-slate-200 py-4 md:hidden">
		<a
			href="/dashboard"
			class="block rounded-md px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
		>
			Dashboard
		</a>

		<div class="space-y-1">
			<div class="px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)]">Transactions</div>
			<a
				href="/transactions/sales"
				class="block rounded-md py-2 pl-8 pr-4 text-sm text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			>
				Sales
			</a>
			<a
				href="/transactions/rentals"
				class="block rounded-md py-2 pl-8 pr-4 text-sm text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			>
				Rentals
			</a>
		</div>

		<a
			href="/analytics"
			class="block rounded-md px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
		>
			Analytics
		</a>

		<a
			href="/projects"
			class="block rounded-md px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
		>
			Projects
		</a>

		<a
			href="/feasibility"
			class="block rounded-md px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
		>
			Feasibility
		</a>

		<hr class="my-2 border-slate-200" />

		<a
			href="/profile"
			class="block rounded-md px-4 py-2.5 text-base font-medium text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
		>
			My Profile
		</a>
		<button
			onclick={handleLogout}
			class="block w-full rounded-md px-4 py-2.5 text-left text-base font-medium text-error transition-colors hover:bg-[var(--color-error-bg)]"
		>
			Sign Out
		</button>
	</div>
{/if}
