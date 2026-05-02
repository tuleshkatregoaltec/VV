<script lang="ts">
const navItems = [
	{ label: 'Platform', href: '#preview' },
	{ label: 'Projects', href: '/projects' },
	{ label: 'Personas', href: '#personas' },
	{ label: 'Pricing', href: '#pricing' }
]
</script>

<nav class="sticky top-0 z-50 border-b border-bone-border bg-bone">
	<div class="mx-auto flex max-w-7xl items-center justify-between px-5 py-[18px] sm:px-8 lg:px-10">
		<a href="/" aria-label="Vitevue home">
			<img
				src="/logos/vitevue-navbar-400.png"
				srcset="/logos/vitevue-navbar-800@2x.png 2x"
				alt="Vitevue"
				class="h-[22px] w-auto"
			/>
		</a>

		<div class="flex items-center gap-6">
			<div class="hidden items-center gap-8 sm:flex">
				{#each navItems as item (item.href)}
					<a
						href={item.href}
						class="border-b border-transparent py-1 text-sm font-medium text-[var(--color-fg-1)] transition-colors duration-150 hover:border-primary"
					>
						{item.label}
					</a>
				{/each}
			</div>
			<a href="/auth" class="hidden text-sm font-medium text-[var(--color-fg-1)] transition-colors hover:text-primary sm:inline">
				Login
			</a>
			<a
				href="/auth"
				class="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-bone transition-colors duration-200 hover:bg-primary-light"
			>
				Get started
				<svg class="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="2"
						d="M13 7l5 5m0 0l-5 5m5-5H6"
					/>
				</svg>
			</a>
		</div>
	</div>
</nav>
