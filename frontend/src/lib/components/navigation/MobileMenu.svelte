<script lang="ts">
	import { fly } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';

	export let show: boolean = false;
</script>

{#if show}
	<div
		class="md:hidden border-t border-primary-pale bg-white/95 backdrop-filter backdrop-blur-xl"
		transition:fly={{ y: -20, duration: 300, easing: quintOut }}
	>
		<div class="px-4 pt-2 pb-4 space-y-1">
			<a
				href="/dashboard"
				class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
			>
				Dashboard
			</a>

			<!-- Transactions Mobile -->
			<div class="space-y-1">
				<div class="px-4 py-2.5 rounded-lg text-base font-medium text-gray-700">Transactions</div>
				<a
					href="/transactions/sales"
					class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
				>
					Sales
				</a>
				<a
					href="/transactions/rentals"
					class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
				>
					Rentals
				</a>
			</div>

			<!-- Analytics Mobile -->
			<div class="space-y-1">
				<div class="px-4 py-2.5 rounded-lg text-base font-medium text-gray-700">Analytics</div>
				<a
					href="/analytics/sales"
					class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
				>
					Sales
				</a>
				<a
					href="/analytics/rentals"
					class="block pl-8 pr-4 py-2 rounded-lg text-sm text-gray-600 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
				>
					Rentals
				</a>
			</div>

					<a
						href="/supply"
						class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
					>
						Supply
					</a>
			<hr class="my-2 border-gray-200" />
			<a
				href="/profile"
				class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
			>
				My Profile
			</a>
			<a
				href="/settings"
				class="block px-4 py-2.5 rounded-lg text-base font-medium text-gray-700 hover:text-primary hover:bg-primary-pale/30 transition-all duration-250"
			>
				Settings
			</a>
			<a
				href="/logout"
				class="block px-4 py-2.5 rounded-lg text-base font-medium text-red-600 hover:bg-red-50 transition-all duration-250"
			>
				Sign Out
			</a>
		</div>
	</div>
{/if}
