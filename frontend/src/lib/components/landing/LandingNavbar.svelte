<script lang="ts">
	const navItems = [
		{ label: 'Preview', href: '#preview' },
		{ label: 'Our Partners', href: '#personas' },
		{ label: 'Pricing', href: '#pricing' },
		{ label: '', href: '#why-vitevue' }
	];
</script>

<nav class="fixed top-0 left-0 right-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-200">
	<div class="container mx-auto px-6 py-3">
		<div class="flex items-center justify-between">
			<a href="/">
				<img src="/logos/v-square-512x512.png" alt="Vitevue" class="h-10 w-auto" />
			</a>

			<div class="flex items-center gap-6">
				{#each navItems as item}
					<a
						href={item.href}
						class="text-sm font-medium text-slate-700 hover:text-slate-900 transition-colors"
					>
						{item.label}
					</a>
				{/each}
				<a
					href="#get-started"
					class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-slate-900 text-white text-sm font-semibold rounded-lg hover:bg-slate-800 hover:scale-105 transition-all"
				>
					Get Started
					<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"></path>
					</svg>
				</a>
			</div>
		</div>
	</div>
</nav>
