<script lang="ts">
import MobileMenu from './MobileMenu.svelte'
import NavDropdown from './NavDropdown.svelte'
import NavLink from './NavLink.svelte'
import ProfileDropdown from './ProfileDropdown.svelte'

let showMobileMenu = $state(false)

const transactionItems = [
	{ href: '/transactions/sales', label: 'Sales' },
	{ href: '/transactions/rentals', label: 'Rentals' }
]
</script>

<nav class="sticky top-0 z-50 border-b border-slate-200 bg-white">
	<div class="mx-auto max-w-screen-2xl px-4 sm:px-6 lg:px-8">
		<div class="flex min-h-[63px] items-center justify-between">
			<div class="flex min-w-0 items-center gap-10">
				<a href="/" class="flex-shrink-0" aria-label="Vitevue home">
					<img
						src="/logos/vitevue-navbar-400.png"
						srcset="/logos/vitevue-navbar-800@2x.png 2x"
						alt="Vitevue"
						class="h-[22px] w-auto"
					/>
				</a>

				<div class="hidden items-center gap-1 md:flex">
					<NavLink href="/dashboard" label="Dashboard" />
					<NavDropdown label="Transactions" items={transactionItems} />
					<NavLink href="/analytics" label="Analytics" />
					<NavLink href="/projects" label="Projects" />
					<NavLink href="/feasibility" label="Feasibility" />
				</div>
			</div>

			<div class="flex items-center flex-shrink-0">
				<div class="hidden md:block">
					<ProfileDropdown />
				</div>

				<button
					onclick={() => (showMobileMenu = !showMobileMenu)}
					class="rounded-md border border-slate-200 p-2 text-slate-700 transition-colors hover:bg-slate-50 md:hidden"
					aria-label="Toggle menu"
				>
					<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
						{#if showMobileMenu}
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M6 18L18 6M6 6l12 12"
							/>
						{:else}
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M4 6h16M4 12h16M4 18h16"
							/>
						{/if}
					</svg>
				</button>
			</div>
		</div>

		<MobileMenu show={showMobileMenu} />
	</div>
</nav>
