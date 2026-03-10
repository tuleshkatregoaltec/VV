<script lang="ts">
const navItems = [
	{ label: 'Preview', href: '#preview' },
	{ label: 'Our Partners', href: '#personas' },
	{ label: 'Pricing', href: '#pricing' }
]
</script>

<nav class="fixed top-4 left-0 right-0 z-50">
	<div class="max-w-screen-2xl mx-auto px-4 sm:px-6 lg:px-8">
		<div
			class="bg-white/95 backdrop-blur-lg rounded-2xl shadow-lg border border-slate-200/50 px-6 py-2.5"
		>
			<div class="flex items-center justify-between">
				<a href="/">
					<img
						src="/logos/vitevue-navbar-400.png"
						srcset="/logos/vitevue-navbar-800@2x.png 2x"
						alt="Vitevue"
						class="h-7 w-auto"
					/>
				</a>

				<div class="flex items-center gap-6">
					<div class="hidden sm:flex items-center gap-6">
						{#each navItems as item (item.href)}
							<a
								href={item.href}
								class="text-sm font-medium text-slate-700 hover:text-slate-900 transition-colors"
							>
								{item.label}
							</a>
						{/each}
					</div>
					<button
						type="button"
						disabled
						class="inline-flex items-center gap-1.5 px-4 py-1.5 bg-slate-200 text-slate-400 text-sm font-semibold rounded-lg cursor-not-allowed"
					>
						Get Started
						<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M13 7l5 5m0 0l-5 5m5-5H6"
							></path>
						</svg>
					</button>
				</div>
			</div>
		</div>
	</div>
</nav>
