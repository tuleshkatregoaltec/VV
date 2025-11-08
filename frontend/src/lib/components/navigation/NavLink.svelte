<script lang="ts">
	import { page } from '$app/state';

	export let href: string;
	export let label: string;
	export let ariaLabel: string = label;
</script>

<a
	{href}
	class="relative px-4 py-2 text-base font-medium text-gray-700 hover:text-primary transition-all duration-300 group"
	aria-current={page.url.pathname === href ? 'page' : undefined}
	aria-label={ariaLabel}
	role="menuitem"
>
	<span class="relative z-10">{label}</span>
	<div
		class="absolute inset-0 bg-primary-pale/30 rounded-lg scale-0 group-hover:scale-100 transition-transform duration-300 origin-center"
	></div>
	<div
		class="absolute bottom-0 left-1/2 -translate-x-1/2 w-0 h-0.5 bg-gradient-to-r from-primary to-primary-dark group-hover:w-3/4 transition-all duration-300"
	></div>
</a>
