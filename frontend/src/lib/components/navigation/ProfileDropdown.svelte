<script module lang="ts">
    let nextId = 0;
</script>

<script lang="ts">
    import { fly, fade } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { page } from '$app/state';
    import { logout } from '$lib/api/auth';
    import { getContext } from 'svelte';

    let initials = $derived((() => {
        const user = page.data.user;
        return user ? `${user.first_name?.[0] ?? ''}${user.last_name?.[0] ?? ''}`.toUpperCase() : '';
    })());

    const HOVER_DELAY = 150;

    // Use shared openDropdownId context so profile dropdown doesn't overlap with others
    let localState = $state<string | null>(null);
    let openDropdownIdContext = getContext<{ value: string | null }>('openDropdownId') ?? {
        get value() { return localState; },
        set value(v: string | null) { localState = v; }
    };

    const id = `profile-dropdown-${nextId++}`;
    let timeout: number | undefined;
    let isOpen = $derived(openDropdownIdContext.value === id);

    function handleEnter() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            openDropdownIdContext.value = id;
        }, HOVER_DELAY);
    }

    function handleLeave() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            if (openDropdownIdContext.value === id) openDropdownIdContext.value = null;
        }, 200);
    }

    function handleLogout() {
        openDropdownIdContext.value = null;
        logout();
    }
</script>

<div 
    class="relative"
    role="navigation"
    onmouseenter={handleEnter}
    onmouseleave={handleLeave}
>
    <button
        class="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white font-semibold text-sm hover:bg-primary/90 transition-colors"
        aria-label="Profile menu"
        aria-haspopup="true"
        aria-expanded={isOpen}
    >
        {initials}
    </button>
    
    {#if isOpen}
        <div 
            class="absolute right-0 mt-1 w-44 bg-white rounded-lg shadow-lg border border-gray-200 py-1 z-50"
            in:fly={{ y: -10, duration: 200, easing: quintOut }}
            out:fade={{ duration: 150 }}
        >
            <a href="/profile" class="block px-3 py-2 text-sm text-gray-700 hover:text-primary hover:bg-gray-50 transition-colors">
                My Profile
            </a>
            <a href="/settings" class="block px-3 py-2 text-sm text-gray-700 hover:text-primary hover:bg-gray-50 transition-colors">
                Settings
            </a>
            <div class="my-1 h-px bg-gray-200"></div>
            <button 
                onclick={handleLogout}
                class="block w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
            >
                Sign Out
            </button>
        </div>
    {/if}
</div>
