<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import { HOVER_OPEN_DELAY, HOVER_CLOSE_DELAY } from '$lib/constants';

	export let initials: string = 'JD';

	let showDropdown = false;
	let openTimeout: number | undefined;
	let closeTimeout: number | undefined;

	function handleMouseEnter() {
		clearTimeout(closeTimeout);
		clearTimeout(openTimeout);
		openTimeout = window.setTimeout(() => {
			showDropdown = true;
		}, HOVER_OPEN_DELAY);
	}

	function handleMouseLeave() {
		clearTimeout(openTimeout);
		closeTimeout = window.setTimeout(() => {
			showDropdown = false;
		}, HOVER_CLOSE_DELAY);
	}
</script>

<div
	class="relative profile-dropdown"
	role="none"
	on:mouseenter={handleMouseEnter}
	on:mouseleave={handleMouseLeave}
>
	<a
		href="/profile"
		class="flex items-center space-x-2 rounded-lg group"
		aria-label="Profile"
		role="menuitem"
	>
		<div
			class="w-9 h-9 rounded-lg bg-gradient-to-br from-primary to-primary-dark flex items-center justify-center text-white font-semibold text-sm shadow-md shadow-primary/30 group-hover:ring-2 group-hover:ring-primary/50 group-hover:ring-offset-2 transition-all duration-300"
		>
			{initials}
		</div>
	</a>

	{#if showDropdown}
		<div
			class="absolute right-0 mt-0 w-56 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl py-2 border border-gray-200/50 overflow-hidden"
			in:fly={{ y: -10, duration: 400, easing: quintOut }}
			out:fade={{ duration: 200 }}
		>
			<a
				href="/profile"
				class="block px-4 py-2.5 text-sm text-gray-700 hover:bg-primary-pale/40 hover:text-primary transition-colors duration-250"
			>
				My Profile
			</a>
			<a
				href="/settings"
				class="block px-4 py-2.5 text-sm text-gray-700 hover:bg-primary-pale/40 hover:text-primary transition-colors duration-250"
			>
				Settings
			</a>
			<div class="my-1 h-px bg-gradient-to-r from-transparent via-gray-200 to-transparent"></div>
			<a
				href="/logout"
				class="block px-4 py-2.5 text-sm text-red-600 hover:bg-red-50 transition-colors duration-250"
			>
				Sign Out
			</a>
		</div>
	{/if}
</div>
