<script lang="ts">
	import { logout } from '$lib/api/auth';

	let {
		show
	}: {
		show: boolean;
	} = $props();

	function handleLogout() {
		logout();
	}
</script>

{#if show}
	<div class="md:hidden border-t border-primary-pale py-4 space-y-1">
		<a
			href="/dashboard"
			class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
		>
			Dashboard
		</a>

		<div class="space-y-1">
			<div class="px-4 py-2.5 text-base font-medium text-gray-700">Transactions</div>
			<a
				href="/transactions/sales"
				class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
			>
				Sales
			</a>
			<a
				href="/transactions/rentals"
				class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
			>
				Rentals
			</a>
		</div>

		<a
			href="/analytics"
			class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
		>
			Analytics
		</a>

		<a
			href="/projects"
			class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
		>
			Projects
		</a>

		<a
			href="/feasibility"
			class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
		>
			Feasibility
		</a>

		<hr class="my-2 border-gray-200" />

		<a
			href="/profile"
			class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-300"
		>
			My Profile
		</a>
		<button
			onclick={handleLogout}
			class="block w-full text-left px-4 py-2.5 rounded-lg text-base font-medium text-red-600 hover:bg-red-50 transition-all duration-300"
		>
			Sign Out
		</button>
	</div>
{/if}
