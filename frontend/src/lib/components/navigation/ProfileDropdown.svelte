<script lang="ts">
    import { fly, fade } from 'svelte/transition';
    import { quintOut } from 'svelte/easing';
    import { authStore } from '$lib/stores/auth.svelte';

    let {
        initials = 'KS'
    }: {
        initials?: string;
    } = $props();

    let showDropdown = $state(false);
    let timeout: number | undefined;

    const HOVER_DELAY = 150;

    function handleEnter() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            showDropdown = true;
        }, HOVER_DELAY);
    }

    function handleLeave() {
        clearTimeout(timeout);
        timeout = window.setTimeout(() => {
            showDropdown = false;
        }, 200);
    }

    function handleLogout() {
        showDropdown = false;
        authStore.logout();
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
        aria-expanded={showDropdown}
    >
        {initials}
    </button>
    
    {#if showDropdown}
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
