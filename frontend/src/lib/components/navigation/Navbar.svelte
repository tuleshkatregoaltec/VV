<script lang="ts">
	import NavLink from './NavLink.svelte';
	import NavDropdown from './NavDropdown.svelte';
	import ProfileMenu from './ProfileMenu.svelte';
	import MobileMenu from './MobileMenu.svelte';

	let showMobileMenu = false;

	function toggleMobileMenu() {
		showMobileMenu = !showMobileMenu;
	}

	const transactionItems = [
		{
			href: '/transactions/sales',
			label: 'Sales',
			icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />'
		},
		{
			href: '/transactions/rentals',
			label: 'Rentals',
			icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />'
		}
	];

	const analyticsItems = [
		{
			href: '/analytics/sales',
			label: 'Sales',
			icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />'
		},
		{
			href: '/analytics/rentals',
			label: 'Rentals',
			icon: '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8v8m-4-5v5m-4-2v2m-2 4h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />'
		}
	];
</script>

<nav
	class="sticky top-0 z-50 backdrop-filter backdrop-blur-xl bg-white/80 shadow-md px-3 sm:px-6"
	aria-label="Main navigation"
>
	<div class="flex justify-between items-center h-16">
		<!-- Left Side: Logo + Navigation Links -->
		<div class="flex items-center space-x-10">
			<!-- Logo/Brand -->
			<a href="/" class="flex items-center group" aria-label="Home">
				<span
					class="text-2xl font-bold bg-gradient-to-r from-primary via-primary-light to-primary-dark bg-clip-text text-transparent group-hover:from-primary group-hover:via-primary-light group-hover:to-primary-dark transition-all duration-300"
				>
					ViteVue
				</span>
				<div
					class="ml-2 w-2 h-2 rounded-full bg-primary group-hover:scale-150 transition-transform duration-300"
				></div>
			</a>

			<!-- Desktop Navigation Links -->
			<div class="hidden md:flex items-center space-x-1" role="menubar" aria-label="Main menu">
				<NavLink href="/dashboard" label="Dashboard" />
				<NavDropdown label="Transactions" items={transactionItems} />
				<NavDropdown label="Analytics" items={analyticsItems} />
				<NavLink href="/supply" label="Supply" />
			</div>
		</div>

		<!-- Right Side: Profile Button (Desktop) -->
		<div class="hidden md:flex items-center" role="none">
			<ProfileMenu initials="KS" />
		</div>

		<!-- Mobile Menu Button -->
		<div class="md:hidden">
			<button
				on:click={toggleMobileMenu}
				class="text-gray-700 hover:text-primary focus:outline-none focus:ring-2 focus:ring-primary rounded-lg p-2 hover:bg-primary-pale/30 transition-all duration-300"
			>
				<svg class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
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
</nav>
