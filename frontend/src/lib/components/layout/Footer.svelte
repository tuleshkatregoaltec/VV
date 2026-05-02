<script lang="ts">
const year = new Date().getFullYear()

const groups = [
	{
		title: 'Platform',
		links: ['Vitevue AI', 'Transactions', 'Analytics', 'Evidence packs']
	},
	{
		title: 'Company',
		links: ['About', 'Careers', 'Contact', 'Press']
	},
	{
		title: 'Legal',
		links: ['Privacy', 'Terms', 'Data sources']
	}
]
</script>

<footer class="border-t border-bone-border bg-bone">
	<div class="mx-auto max-w-7xl px-5 py-16 sm:px-8 lg:px-10">
		<div class="grid gap-12 lg:grid-cols-[1.4fr_1fr_1fr_1fr] lg:gap-16">
			<div>
				<img
					src="/logos/vitevue-navbar-400.png"
					srcset="/logos/vitevue-navbar-800@2x.png 2x"
					alt="Vitevue"
					class="h-[22px] w-auto"
				/>
				<p class="mt-5 max-w-sm text-sm leading-relaxed text-[var(--color-fg-3)]">
					AI-native real estate intelligence for Dubai. Tactical comps, institutional outputs.
				</p>
			</div>

			{#each groups as group (group.title)}
				<div>
					<h2
						class="mb-5 text-[11px] font-medium uppercase tracking-[0.18em] text-[var(--color-fg-4)]"
					>
						{group.title}
					</h2>
					<ul class="space-y-3">
						{#each group.links as link (link)}
							<li>
								<a href="/" class="text-sm text-[var(--color-fg-2)] transition-colors hover:text-[var(--color-fg-1)]">
									{link}
								</a>
							</li>
						{/each}
					</ul>
				</div>
			{/each}
		</div>

		<div
			class="mt-14 flex flex-col gap-3 border-t border-bone-border pt-6 text-xs text-[var(--color-fg-4)] sm:flex-row sm:items-center sm:justify-between"
		>
			<span>&copy; {year} Vitevue L.L.C-FZ. All rights reserved.</span>
			<span>Dubai real estate intelligence</span>
		</div>
	</div>
</footer>
