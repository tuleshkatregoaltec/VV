<script module lang="ts">
let nextId = 0
</script>

<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import { logout } from '$lib/api/auth';
	import { getContext } from 'svelte';
	import { currentUser } from '$lib/stores/user.svelte';

	let initials = $derived(
		(() => {
			const user = currentUser.data;
			return user ? `${user.first_name?.[0] ?? ''}${user.last_name?.[0] ?? ''}`.toUpperCase() : '';
		})()
	);

	const HOVER_DELAY = 150;

	// Use shared openDropdownId context so profile dropdown doesn't overlap with others
	let localState = $state<string | null>(null);
	let openDropdownIdContext = getContext<{ value: string | null }>('openDropdownId') ?? {
		get value() {
			return localState;
		},
		set value(v: string | null) {
			localState = v;
		}
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

<div class="relative" role="navigation" onmouseenter={handleEnter} onmouseleave={handleLeave}>
	<button
		class="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-sm font-semibold tracking-[0.02em] text-bone transition-colors hover:bg-primary-light"
		aria-label="Profile menu"
		aria-haspopup="true"
		aria-expanded={isOpen}
	>
		{initials}
	</button>

	{#if isOpen}
		<div
			class="absolute right-0 z-50 mt-1 w-44 rounded-lg border border-slate-200 bg-white py-1 shadow-[var(--shadow-md)]"
			in:fly={{ y: -10, duration: 200, easing: quintOut }}
			out:fade={{ duration: 150 }}
		>
			<a
				href="/profile"
				class="block px-3 py-2 text-sm text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			>
				My Profile
			</a>
			<a
				href="/settings/organization"
				class="block px-3 py-2 text-sm text-[var(--color-fg-3)] transition-colors hover:bg-slate-50 hover:text-[var(--color-fg-1)]"
			>
				Organization
			</a>
			<div class="my-1 h-px bg-slate-200"></div>
			<button
				onclick={handleLogout}
				class="block w-full px-3 py-2 text-left text-sm text-error transition-colors hover:bg-[var(--color-error-bg)]"
			>
				Sign Out
			</button>
		</div>
	{/if}
</div>
