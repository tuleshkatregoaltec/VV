<script lang="ts">
export let title: string
export let subtitle: string = ''
export let gradient: boolean = true
</script>

<header class="pt-18 mb-12 text-center">
	{#if gradient}
		<h1
			class="text-4xl sm:text-5xl font-bold bg-gradient-to-r from-primary via-primary-light to-primary-dark bg-clip-text text-transparent mb-2"
		>
			{title}
		</h1>
	{:else}
		<h1 class="text-4xl sm:text-5xl font-bold text-gray-900 mb-2">
			{title}
		</h1>
	{/if}
	{#if subtitle}
		<p class="text-gray-500 text-base font-medium">{subtitle}</p>
	{/if}
</header>
