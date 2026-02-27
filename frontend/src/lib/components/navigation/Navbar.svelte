<script lang="ts">
    import NavLink from './NavLink.svelte';
    import NavDropdown from './NavDropdown.svelte';
    import ProfileDropdown from './ProfileDropdown.svelte';
    import MobileMenu from './MobileMenu.svelte';

    let showMobileMenu = $state(false);

    const transactionItems = [
        { href: '/transactions/sales', label: 'Sales' },
        { href: '/transactions/rentals', label: 'Rentals' }
    ];

</script>

<nav class="fixed top-4 left-0 right-0 z-50">
    <div class="max-w-screen-2xl mx-auto px-4">
        <div class="bg-white/95 backdrop-blur-lg rounded-2xl shadow-lg border border-slate-200/50 px-6 py-2.5">
            <div class="flex items-center justify-between">
                <a href="/" class="flex-shrink-0">
                    <img
                        src="/logos/vitevue-navbar-400.png"
                        srcset="/logos/vitevue-navbar-800@2x.png 2x"
                        alt="Vitevue"
                        class="h-7 w-auto"
                    />
                </a>

                <div class="hidden md:flex items-center gap-2 ml-8 flex-1">
                    <NavLink href="/dashboard" label="Dashboard" />
                    <NavDropdown label="Transactions" items={transactionItems} />
                    <NavLink href="/analytics" label="Analytics" />
                    <NavLink href="/projects" label="Projects" />
                    <NavLink href="/feasibility" label="Feasibility" />
                </div>

                <div class="flex items-center flex-shrink-0">
                    <div class="hidden md:block">
                        <ProfileDropdown />
                    </div>

                    <button
                        onclick={() => showMobileMenu = !showMobileMenu}
                        class="md:hidden p-2"
                        aria-label="Toggle menu"
                    >
                        <svg class="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            {#if showMobileMenu}
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                            {:else}
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
                            {/if}
                        </svg>
                    </button>
                </div>
            </div>

            <MobileMenu show={showMobileMenu} />
        </div>
    </div>
</nav>
