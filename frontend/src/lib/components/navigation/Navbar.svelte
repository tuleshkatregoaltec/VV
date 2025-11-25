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

    const analyticsItems = [
        { href: '/analytics/sales', label: 'Sales' },
        { href: '/analytics/rentals', label: 'Rentals' }
    ];
</script>

<nav class="sticky top-0 z-50 bg-white border-b border-gray-200">
    <div class="flex items-center justify-between h-16 px-8">
        <!-- Logo -->
        <a href="/" class="flex items-center gap-2 flex-shrink-0">
            <span class="text-xl font-bold text-gray-900">Vitevue</span>
            <div class="w-1.5 h-1.5 rounded-full bg-primary"></div>
        </a>

        <!-- Desktop Nav - Left aligned after logo -->
        <div class="hidden md:flex items-center gap-2 ml-8 flex-1">
            <NavLink href="/dashboard" label="Dashboard" />
            <NavDropdown label="Transactions" items={transactionItems} />
            <NavDropdown label="Analytics" items={analyticsItems} />
            <NavLink href="/supply" label="Supply" />
        </div>

        <!-- Profile / Mobile Button -->
        <div class="flex items-center flex-shrink-0">
            <div class="hidden md:block">
                <ProfileDropdown initials="KS" />
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
</nav>
