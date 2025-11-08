<script lang="ts">
	import { fly, fade } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import { HOVER_OPEN_DELAY, HOVER_CLOSE_DELAY } from '$lib/constants';

	export let label: string;
	export let items: Array<{ href: string; label: string; icon: string }>;

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
	class="relative {label.toLowerCase()}-dropdown"
	on:mouseenter={handleMouseEnter}
	on:mouseleave={handleMouseLeave}
	role="none"
>
	<button
		class="relative px-4 py-2 text-base font-medium text-gray-700 hover:text-primary transition-all duration-300 group flex items-center"
		aria-haspopup="true"
		aria-expanded={showDropdown}
		aria-controls="{label.toLowerCase()}-menu"
		aria-label="Open {label.toLowerCase()} menu"
		type="button"
		role="menuitem"
	>
		<span class="relative z-10">{label}</span>
		<svg
			class="ml-1 w-4 h-4"
			fill="none"
			viewBox="0 0 24 24"
			stroke="currentColor"
			aria-hidden="true"
		>
			<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
		</svg>
		<div
			class="absolute inset-0 bg-primary-pale/30 rounded-lg scale-0 group-hover:scale-100 transition-transform duration-300 origin-center"
		></div>
		<div
			class="absolute bottom-0 left-1/2 -translate-x-1/2 w-0 h-0.5 bg-gradient-to-r from-primary to-primary-dark group-hover:w-3/4 transition-all duration-300"
		></div>
	</button>

	{#if showDropdown}
		<div
			id="{label.toLowerCase()}-menu"
			class="absolute left-1/2 -translate-x-1/2 mt-0 w-56 bg-white/95 backdrop-blur-sm rounded-xl shadow-2xl py-2 border border-gray-200/50 overflow-hidden"
			in:fly={{ y: -10, duration: 400, easing: quintOut }}
			out:fade={{ duration: 200 }}
			role="menu"
			aria-label="{label} submenu"
		>
			{#each items as item (item.href)}
				<a
					href={item.href}
					class="block px-4 py-2.5 text-sm text-gray-700 hover:bg-primary-pale/40 hover:text-primary transition-colors duration-250 flex items-center"
					role="menuitem"
				>
					<svg
						class="w-4 h-4 mr-3"
						fill="none"
						viewBox="0 0 24 24"
						stroke="currentColor"
						aria-hidden="true"
					>
						{@html item.icon}
					</svg>
					{item.label}
				</a>
			{/each}
		</div>
	{/if}
</div>
