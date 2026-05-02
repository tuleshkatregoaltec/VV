<script lang="ts">
export let title: string
export let subtitle: string = ''
</script>

<header class="pt-18 mb-12 text-center">
	<h1 class="text-4xl sm:text-5xl font-semibold text-[var(--color-fg-1)] mb-2">
		{title}
	</h1>
	{#if subtitle}
		<p class="text-[var(--color-fg-3)] text-base font-medium">{subtitle}</p>
	{/if}
</header>
